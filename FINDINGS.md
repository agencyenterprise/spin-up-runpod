# RunPod API Gotchas

## Critical: SSH Keys Required

Pods created via API **will not have SSH access** unless you explicitly add your SSH public keys as an environment variable:

```python
env_vars = [{"key": "PUBLIC_KEY", "value": your_ssh_keys}]
```

The web UI does this automatically. The API does not.

Query your account's SSH keys:
```graphql
query {
  myself {
    pubKey
  }
}
```

## Network Volume Attachment

Use `networkVolumeId` (not `volumeKey`):

```python
input_data["networkVolumeId"] = "wup549p1f2"
```

When using a template, **do not** specify `volumeMountPath` - let the template handle it.

## Template Usage

Template IDs like `runpod-torch-v280` are real IDs, not just names.

When using a template:
- **Do specify**: `templateId`, `gpuTypeId`, `gpuCount`, `networkVolumeId`, `env` (with SSH keys)
- **Don't specify**: `containerDiskInGb`, `ports`, `imageName`, `volumeMountPath` (template defines these)

## Field Names

GraphQL uses:
- `podTemplates` (not `templates`)
- `networkVolumeId` (for attaching existing volumes)
- `volumeInGb` (for creating NEW pod volumes)

