#!/usr/bin/env python3
"""
RunPod Automation Script

Automates the process of:
1. Creating a new RunPod instance
2. Configuring SSH access
3. Setting up Python environment
4. Installing project dependencies
"""

import os
import sys
import time
import yaml
import json
import subprocess
from pathlib import Path
from dotenv import load_dotenv
import requests

# Load environment variables
load_dotenv()

RUNPOD_API_KEY = os.getenv("RUNPOD_API_KEY")
if not RUNPOD_API_KEY:
    print("❌ Error: RUNPOD_API_KEY not found in .env file")
    sys.exit(1)

RUNPOD_API_URL = "https://api.runpod.io/graphql"


def graphql_query(query, variables=None):
    """Execute a GraphQL query against RunPod API."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {RUNPOD_API_KEY}"
    }
    
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    
    response = requests.post(RUNPOD_API_URL, json=payload, headers=headers)
    response.raise_for_status()
    
    result = response.json()
    if "errors" in result:
        print(f"❌ GraphQL Error: {json.dumps(result['errors'], indent=2)}")
        raise Exception(f"GraphQL query failed: {result['errors']}")
    
    return result["data"]


def get_ssh_keys():
    """Retrieve SSH public keys from RunPod account."""
    query = """
    query {
        myself {
            pubKey
        }
    }
    """
    
    data = graphql_query(query)
    return data["myself"]["pubKey"]


def get_network_volume_datacenter(volume_id):
    """Get the datacenter ID for a network volume."""
    query = """
    query {
        myself {
            networkVolumes {
                id
                dataCenterId
            }
        }
    }
    """
    
    data = graphql_query(query)
    volumes = data["myself"]["networkVolumes"]
    
    for volume in volumes:
        if volume["id"] == volume_id:
            return volume["dataCenterId"]
    
    return None


def create_pod(config):
    """Create a new RunPod instance based on config."""
    print(f"\n🚀 Creating pod: {config['pod_name']}")
    
    # Get SSH keys
    ssh_keys = get_ssh_keys()
    print("✓ Retrieved SSH keys from account")
    
    # Get datacenter from network volume (if provided)
    network_volume_id = config.get("network_volume_id")
    datacenter_id = None
    
    if network_volume_id:
        datacenter_id = get_network_volume_datacenter(network_volume_id)
        if datacenter_id:
            print(f"✓ Detected datacenter: {datacenter_id} (from network volume)")
        else:
            print("⚠️  Could not detect datacenter from network volume")
    else:
        print("✓ No network volume specified - searching all datacenters")
    
    # Prepare environment variables (critical for SSH access!)
    env_vars = [{"key": "PUBLIC_KEY", "value": ssh_keys}]
    
    # Build the mutation
    mutation = """
    mutation CreatePod($input: PodFindAndDeployOnDemandInput!) {
        podFindAndDeployOnDemand(input: $input) {
            id
            desiredStatus
            imageName
            env
            machineId
            machine {
                gpuDisplayName
            }
        }
    }
    """
    
    # Prepare input data based on FINDINGS.md recommendations
    input_data = {
        "cloudType": "ALL",
        "gpuTypeId": config["gpu_type"],
        "gpuCount": config["num_gpus"],
        "name": config["pod_name"],
        "templateId": config["template_id"],
        "env": env_vars
    }
    
    # Add network volume if provided  
    if network_volume_id:
        input_data["networkVolumeId"] = network_volume_id
        # Container disk (root filesystem at /) - separate from network volume at /workspace
        input_data["containerDiskInGb"] = config.get("disk_space_gb", 200)
        print(f"✓ Configuring container disk: {input_data['containerDiskInGb']}GB (for root /)")
        print(f"✓ Using network volume: {network_volume_id} (for /workspace)")
    else:
        # Without network volume, specify disk storage
        # Templates handle SSH port exposure automatically
        input_data["volumeInGb"] = config.get("disk_space_gb", 200)
        print(f"✓ Configuring pod disk: {input_data['volumeInGb']}GB (no network volume)")
    
    # Add datacenter (automatically detected from network volume)
    if datacenter_id:
        input_data["dataCenterId"] = datacenter_id
    
    # Note: Templates handle SSH port exposure and image configuration automatically
    # containerDiskInGb controls the root (/) filesystem size, separate from network volume
    
    variables = {"input": input_data}
    
    print(f"✓ Requesting {config['num_gpus']}x {config['gpu_type']} GPU(s)")
    
    data = graphql_query(mutation, variables)
    pod = data["podFindAndDeployOnDemand"]
    
    print(f"✅ Pod created! ID: {pod['id']}")
    print(f"   GPU: {pod['machine']['gpuDisplayName']}")
    
    return pod["id"]


def wait_for_pod_ready(pod_id):
    """Poll the pod until it's running and has SSH details."""
    print(f"\n⏳ Waiting for pod {pod_id} to be ready...")
    
    query = """
    query Pod($podId: String!) {
        pod(input: {podId: $podId}) {
            id
            desiredStatus
            runtime {
                uptimeInSeconds
                ports {
                    ip
                    isIpPublic
                    privatePort
                    publicPort
                    type
                }
            }
        }
    }
    """
    
    while True:
        try:
            data = graphql_query(query, {"podId": pod_id})
            pod = data["pod"]
            
            if pod["runtime"] and pod["runtime"]["ports"]:
                # Find SSH port (22)
                for port in pod["runtime"]["ports"]:
                    if port["privatePort"] == 22 and port["isIpPublic"]:
                        ssh_ip = port["ip"]
                        ssh_port = port["publicPort"]
                        print("✅ Pod is ready!")
                        print(f"   SSH: {ssh_ip}:{ssh_port}")
                        return ssh_ip, ssh_port
            
            print(f"   Status: {pod['desiredStatus']} - waiting...")
            time.sleep(5)
            
        except Exception as e:
            print(f"   Polling error: {e} - retrying...")
            time.sleep(5)


def update_ssh_config(pod_name, ssh_ip, ssh_port):
    """Update ~/.ssh/config with the new pod details."""
    ssh_config_path = Path.home() / ".ssh" / "config"
    
    # Sanitize pod name for SSH config (no spaces allowed)
    ssh_host_name = pod_name.replace(" ", "-")
    
    if ssh_host_name != pod_name:
        print(f"   Note: SSH host name sanitized to '{ssh_host_name}' (spaces → dashes)")
    
    # Create host entry
    host_entry = f"""
Host {ssh_host_name}
    HostName {ssh_ip}
    Port {ssh_port}
    User root
    IdentityFile ~/.ssh/id_ed25519
    StrictHostKeyChecking accept-new
"""
    
    # Read existing config
    if ssh_config_path.exists():
        with open(ssh_config_path, "r") as f:
            existing_config = f.read()
        
        # Check if host already exists and remove it
        lines = existing_config.split("\n")
        new_lines = []
        skip_until_next_host = False
        
        for line in lines:
            if line.startswith("Host "):
                if ssh_host_name in line:
                    skip_until_next_host = True
                else:
                    skip_until_next_host = False
                    new_lines.append(line)
            elif not skip_until_next_host:
                new_lines.append(line)
        
        existing_config = "\n".join(new_lines).rstrip()
    else:
        existing_config = ""
    
    # Append new entry
    with open(ssh_config_path, "w") as f:
        if existing_config:
            f.write(existing_config)
            f.write("\n")
        f.write(host_entry)
    
    print("✅ Updated SSH config: ~/.ssh/config")
    print(f"   You can now connect with: ssh {ssh_host_name}")
    
    return ssh_host_name  # Return the sanitized name for use in other functions


def wait_for_ssh(pod_name, max_attempts=30):
    """Wait for SSH to become available."""
    print("\n⏳ Waiting for SSH to become available...")
    
    for attempt in range(max_attempts):
        try:
            result = subprocess.run(
                ["ssh", "-o", "ConnectTimeout=5", pod_name, "echo", "ready"],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0 and "ready" in result.stdout:
                print("✅ SSH is ready!")
                return True
            
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            pass
        
        print(f"   Attempt {attempt + 1}/{max_attempts}...")
        time.sleep(5)
    
    print(f"❌ SSH did not become available after {max_attempts} attempts")
    return False


def setup_remote_environment(pod_name, config):
    """Setup Python environment on the remote pod."""
    print("\n🔧 Setting up remote environment...")
    
    venv_path = config["venv_path"]
    requirements_file = config["requirements_file"]
    
    commands = [
        # Create venv
        f"python3 -m venv {venv_path}",
        
        # Upgrade pip
        f"{venv_path}/bin/pip install --upgrade pip",
        
        # Install requirements if file exists
        f"if [ -f {requirements_file} ]; then {venv_path}/bin/pip install -r {requirements_file}; else echo 'Requirements file not found: {requirements_file}'; fi"
    ]
    
    # Add git configuration if user details are provided
    user_email = config.get("user_email")
    user_name = config.get("user_name")
    if user_email:
        commands.append(f'git config --global user.email "{user_email}"')
    if user_name:
        commands.append(f'git config --global user.name "{user_name}"')
    
    for i, cmd in enumerate(commands, 1):
        print(f"\n   [{i}/{len(commands)}] Running: {cmd[:80]}...")
        
        result = subprocess.run(
            ["ssh", pod_name, cmd],
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print(f"   ⚠️  Command failed (exit code {result.returncode})")
            if result.stderr:
                print(f"   Error: {result.stderr[:200]}")
        else:
            print("   ✓ Success")
    
    print("\n✅ Remote environment setup complete!")
    print(f"   Virtual environment: {venv_path}")
    print(f"   Python interpreter: {venv_path}/bin/python")


def check_code_server_exists(pod_name):
    """Check if code-server/cursor-server exists on the remote."""
    check_cmd = """
if [ -d ~/.vscode-server/bin ] || [ -d ~/.cursor-server/bin ]; then
    # Look for server binaries
    if find ~/.vscode-server/bin ~/.cursor-server/bin -name 'code-server' -o -name 'cursor-server' 2>/dev/null | grep -q .; then
        exit 0
    fi
fi
exit 1
"""
    try:
        result = subprocess.run(
            ["ssh", pod_name, check_cmd],
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.returncode == 0
    except Exception:
        return False


def wait_for_code_server(pod_name, max_wait=180):
    """Wait for user to connect with Cursor/VS Code so code-server gets installed."""
    print("\n⏳ Waiting for Cursor/VS Code connection...")
    print("   (If you haven't connected yet, please do so now!)\n")
    
    start_time = time.time()
    check_interval = 5
    
    while time.time() - start_time < max_wait:
        if check_code_server_exists(pod_name):
            print("✅ Code server detected! Continuing with extension installation...")
            return True
        
        elapsed = int(time.time() - start_time)
        remaining = max_wait - elapsed
        print(f"   Checking for code-server... ({elapsed}s elapsed, {remaining}s remaining)", end='\r')
        time.sleep(check_interval)
    
    print(f"\n⏱️  Timeout after {max_wait}s - code-server not detected")
    return False


def install_vscode_extensions(pod_name, extensions):
    """Install VS Code extensions on the remote via SSH."""
    print("\n🔌 Installing VS Code extensions on remote...")
    
    # First check if code-server exists
    if not check_code_server_exists(pod_name):
        # Wait for user to connect (they should have already started)
        if not wait_for_code_server(pod_name):
            print("\n⏭️  Skipping extension installation")
            print("   Extensions can be installed manually after connecting:")
            print(f"   cursor --remote ssh-remote+{pod_name} --install-extension ms-python.python")
            return False
    else:
        print("✓ Code server detected")
    
    # Now install extensions
    for ext in extensions:
        print(f"\n   Installing {ext}...")
        
        install_cmd = f"""
# Find the code-server binary
CODE_SERVER=$(find ~/.vscode-server/bin ~/.cursor-server/bin -name 'code-server' -o -name 'cursor-server' 2>/dev/null | head -1)
if [ -n "$CODE_SERVER" ]; then
    "$CODE_SERVER" --install-extension {ext} 2>&1
else
    echo "ERROR: Could not find code-server binary"
    exit 1
fi
"""
        
        try:
            result = subprocess.run(
                ["ssh", pod_name, install_cmd],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0:
                print(f"   ✓ Installed {ext}")
                if result.stdout and "already installed" not in result.stdout.lower():
                    print(f"      {result.stdout.strip()[:100]}")
            else:
                print(f"   ⚠️  Failed to install {ext}")
                if result.stdout:
                    print(f"      {result.stdout[:150]}")
        except subprocess.TimeoutExpired:
            print(f"   ⚠️  Timeout installing {ext}")
        except Exception as e:
            print(f"   ⚠️  Error installing {ext}: {e}")
    
    print("\n✅ Extension installation complete!")
    return True


def create_vscode_settings_remote(ssh_host_name, config):
    """Create VS Code settings file directly in the remote workspace."""
    print("\n📝 Configuring VS Code settings on remote...")
    
    # Infer workspace directory from requirements_file path
    requirements_path = config.get("requirements_file", "")
    if requirements_path and requirements_path.startswith("/workspace/"):
        # Extract workspace dir (e.g., /workspace/my-project from /workspace/my-project/requirements.txt)
        workspace_dir = "/".join(requirements_path.split("/")[:-1])
    else:
        # Default to /workspace
        workspace_dir = "/workspace"
        print(f"   ⚠️  Could not infer workspace from requirements_file, using {workspace_dir}")
    
    settings = {
        "python.defaultInterpreterPath": f"{config['venv_path']}/bin/python",
        "python.terminal.activateEnvironment": True,
    }
    
    settings_json = json.dumps(settings, indent=2)
    
    # Create .vscode directory and settings.json on remote
    create_cmd = f"""
mkdir -p {workspace_dir}/.vscode
cat > {workspace_dir}/.vscode/settings.json << 'EOF'
{settings_json}
EOF
echo "Settings created in {workspace_dir}/.vscode/settings.json"
"""
    
    try:
        result = subprocess.run(
            ["ssh", ssh_host_name, create_cmd],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            print(f"✅ Created settings in {workspace_dir}/.vscode/settings.json")
            print(f"   Python interpreter will auto-select: {config['venv_path']}/bin/python")
            return True
        else:
            print("   ⚠️  Could not create remote settings file")
            if result.stderr:
                print(f"      {result.stderr[:100]}")
            return False
    except Exception as e:
        print(f"   ⚠️  Error creating remote settings: {e}")
        return False


def main():
    if len(sys.argv) != 2:
        print("Usage: python spin_up_runpod.py <config.yaml>")
        sys.exit(1)
    
    config_file = sys.argv[1]
    
    # Load configuration
    with open(config_file, "r") as f:
        config = yaml.safe_load(f)
    
    print("🎯 RunPod Automation Script")
    print("=" * 50)
    print(f"Config: {config_file}")
    print(f"Pod Name: {config['pod_name']}")
    print(f"Template: {config['template_id']}")
    
    try:
        # Phase 1: Create pod
        pod_id = create_pod(config)
        
        # Phase 2: Wait for pod to be ready
        ssh_ip, ssh_port = wait_for_pod_ready(pod_id)
        
        # Phase 3: Update SSH config (returns sanitized host name)
        ssh_host_name = update_ssh_config(config["pod_name"], ssh_ip, ssh_port)
        
        # Phase 4: Wait for SSH (use sanitized host name)
        if not wait_for_ssh(ssh_host_name):
            print("\n⚠️  Warning: Could not verify SSH access")
            print("   You may need to wait a bit longer and try manually")
        else:
            # Prompt user to connect with Cursor now (while we do environment setup)
            extensions = config.get("vscode_extensions", [])
            if extensions:
                print("\n" + "=" * 70)
                print("📋 NEXT STEP - Open Cursor now!")
                print("=" * 70)
                print("\n👉 While environment setup runs, please connect with Cursor:")
                print("   • Open Cursor")
                print("   • Press Cmd+Shift+P → 'Remote-SSH: Connect to Host'")
                print(f"   • Select: {ssh_host_name}")
                print(f"\n   OR run: cursor --remote ssh-remote+{ssh_host_name} /workspace")
                print("\n" + "=" * 70)
                
                # Wait for user acknowledgment
                try:
                    input("\n⏸️  Press ENTER to continue (after you've started connecting)... ")
                except KeyboardInterrupt:
                    print("\n\n⚠️  Interrupted by user")
                    sys.exit(1)
                
                print("\n⏳ Continuing with environment setup...\n")
            
            # Phase 5: Setup remote environment (pip install happens here)
            setup_remote_environment(ssh_host_name, config)
            
            # Phase 6: Install VS Code extensions (if specified)
            extensions = config.get("vscode_extensions", [])
            if extensions:
                install_vscode_extensions(ssh_host_name, extensions)
            else:
                print("\n⏭️  No VS Code extensions specified, skipping installation")
            
            # Phase 7: Create VS Code settings on remote
            create_vscode_settings_remote(ssh_host_name, config)
        
        print("\n" + "=" * 50)
        print("🎉 Setup complete! Your RunPod is ready to use!")
        print("=" * 50)
        
        # Check if extensions were installed
        extensions_installed = config.get("vscode_extensions", []) and check_code_server_exists(ssh_host_name)
        
        if extensions_installed:
            print("\n✅ Everything is configured:")
            print(f"   • SSH access: ssh {ssh_host_name}")
            print(f"   • Python environment: {config['venv_path']}")
            print("   • Dependencies installed from requirements.txt")
            print("   • VS Code extensions installed")
            print("   • Python interpreter configured")
            print("\n🚀 Your Cursor/VS Code window should be ready to code!")
            print("   The Python interpreter should auto-select when you open the workspace.")
        else:
            print("\n✅ Environment configured:")
            print(f"   • SSH access: ssh {ssh_host_name}")
            print(f"   • Python environment: {config['venv_path']}")
            print("   • Dependencies installed from requirements.txt")
            print("   • Python interpreter configured")
            print("\n💡 Next: Install Python extension via Extensions panel in Cursor")
            print("   Then the interpreter should auto-select!")
        
        print(f"\n📦 Pod ID: {pod_id}")
        print(f"💰 Remember to terminate when done: python manage_pods.py terminate {pod_id}")
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

