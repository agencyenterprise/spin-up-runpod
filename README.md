# RunPod Automation

Automate the entire process of creating and setting up a new RunPod instance - from API calls to environment configuration in one command.

## ✨ Features

- 🚀 Creates RunPod instance via API with your specs
- 🔑 Automatically configures SSH keys and updates `~/.ssh/config`
- 🐍 Creates Python virtual environment and installs dependencies
- 🔌 Installs VS Code extensions (Python, etc.)
- 📍 Auto-detects datacenter from your network volume
- ⏱️ **Saves ~10-15 minutes of manual setup per pod**

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set Your API Key

Create a `.env` file:
```bash
RUNPOD_API_KEY=your_api_key_here
```

### 3. Find Your GPU Type

```bash
python list_gpus.py
```

Copy the **exact GPU ID** (e.g., `NVIDIA A100 80GB PCIe`, not just `A100`).

### 4. Configure Your Pod

Edit `example_config.yaml`:

```yaml
disk_space_gb: 200
gpu_type: NVIDIA A100 80GB PCIe  # Use exact GPU type ID from list_gpus.py
num_gpus: 1
network_volume_id: xvq549q1g2
pod_name: My-Project
requirements_file: /workspace/my-project/requirements.txt
template_id: runpod-torch-v280
venv_path: /tmp/venv
vscode_extensions:
  - ms-python.python
```

### 5. Run It!

```bash
python setup_runpod.py example_config.yaml
```

The script will:
1. Create the pod
2. Configure SSH
3. Prompt you to **open Cursor/VS Code** (do this while it continues)
4. Set up Python environment (while you're connecting)
5. Install extensions automatically
6. Report completion

**Time**: ~3-5 minutes total. You open Cursor while pip is installing, then everything's ready!

## Configuration Reference

| Field | Description | Example |
|-------|-------------|---------|
| `disk_space_gb` | Disk space (reference only) | `200` |
| `gpu_type` | **Exact** GPU type ID | `NVIDIA A100 80GB PCIe` |
| `num_gpus` | Number of GPUs | `1` |
| `network_volume_id` | Your network volume ID | `xvq549q1g2` |
| `pod_name` | Pod name (spaces → dashes in SSH) | `My-Project` |
| `requirements_file` | Path to requirements.txt on remote | `/workspace/project/requirements.txt` |
| `template_id` | RunPod template ID | `runpod-torch-v280` |
| `venv_path` | Where to create venv | `/tmp/venv` |
| `vscode_extensions` | List of extension IDs (optional) | `["ms-python.python"]` |

**Notes**:
- Datacenter is automatically detected from your network volume
- Pod names with spaces get sanitized for SSH (e.g., "My Pod" → "My-Pod")
- Omit `vscode_extensions` or use `[]` to skip extension installation

## Discovery Tools

### List GPUs
```bash
python list_gpus.py
```
Shows all available GPU types with exact IDs needed for config.

### List Datacenters
```bash
python list_datacenters.py
```
Shows your network volumes and their datacenter locations.

## Managing Pods

```bash
# List all your pods
python manage_pods.py list

# Get details about a pod
python manage_pods.py details <pod_id>

# Stop a pod (keeps it for later)
python manage_pods.py stop <pod_id>

# Terminate (delete) a pod
python manage_pods.py terminate <pod_id>
```

## Troubleshooting

### "No instances available"
1. Use **exact GPU type ID**: Run `python list_gpus.py`
   - ❌ Wrong: `A100`
   - ✅ Right: `NVIDIA A100 80GB PCIe`
2. Try a different GPU type
3. Check RunPod web UI for current availability
4. Wait and retry (availability changes frequently)

### SSH Not Working
- Wait 30-60 more seconds (pods take time to boot)
- Check pod status: `python manage_pods.py list`
- Verify SSH key is in your RunPod account settings

### Requirements Installation Failed
- Ensure `requirements_file` path is correct
- Path should point to network volume: `/workspace/<project>/requirements.txt`

### Extensions Not Installing
- Make sure you opened Cursor/VS Code when prompted
- Extensions need code-server (installed on first connection)
- Install manually via Extensions panel if needed

## Advanced Usage

### Multiple Projects
Create different YAML files:
```bash
python setup_runpod.py project1.yaml
python setup_runpod.py project2.yaml
```

### Custom Extensions
```yaml
vscode_extensions:
  - ms-python.python
  - ms-python.vscode-pylance
  - ms-toolsai.jupyter
  - github.copilot
```

### Custom Setup
Edit `setup_remote_environment()` in the script to add:
- System package installation
- Repository cloning
- Environment variables
- Initialization scripts

## How It Works

1. **Pod Creation**: Queries SSH keys, detects datacenter, creates pod via API
2. **SSH Configuration**: Updates `~/.ssh/config` with connection details
3. **Environment Setup**: Creates venv, installs pip packages (you connect during this)
4. **Extension Installation**: Automatically installs VS Code extensions once code-server is ready
5. **Ready to Code**: Everything configured, just start coding!

## See Also

- `FINDINGS.md` - Important notes about RunPod API quirks
- RunPod API docs: https://graphql-spec.runpod.io/
