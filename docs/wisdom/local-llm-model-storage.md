# Local LLM model storage
<!-- doc-status: active -->

**Status:** stable  
**Applies to:** projects using local LLM runners (Ollama, LM Studio, mlx-lm)  
**Portable:** yes

## Two independent failure modes

When using external disk storage for local LLM models on macOS, two structurally unrelated problems can occur.

### Problem 1: exFAT filesystem incompatibility

macOS extended attributes (xattr) are not supported on exFAT-formatted disks. When a model daemon or tool manages model blobs on an exFAT volume, it may generate AppleDouble sidecar files (`._<modelname>`) to work around the missing xattr support. These files show up as "corrupt manifest detected" warnings in daemon logs and can cause intermittent load failures.

**This is a filesystem-format problem**, not a symlink problem — it persists even if you point the daemon directly at the external path via a native environment variable, as long as that path is on exFAT.

### Problem 2: Symlinked model storage

A model directory symlink pointing at an external drive (especially one that may not be mounted at startup) creates a distinct failure mode. Even when the daemon itself is healthy and responding to pings, model load attempts can time out waiting for the mount.

**This is a mount-timing problem**, not a filesystem issue — it persists even if the target volume is APFS.

## Two independent fixes

| Fix | Addresses | Does NOT address |
|-----|-----------|------------------|
| Use daemon's native `*_MODELS` env var (e.g., `OLLAMA_MODELS`) instead of a symlink | Problem 2 (symlink indirection) | Problem 1 (exFAT format) |
| Format external volume as APFS | Problem 1 (exFAT format) | Problem 2 (symlink indirection) |

Use both together if your model storage is external and your filesystem is exFAT. Using one alone leaves the other problem unsolved.

### Setting up the native env var (macOS)

For Ollama, set `OLLAMA_MODELS` via `launchd` (since GUI apps on macOS don't inherit shell rc files):

1. Find the Ollama `launchd` plist (typically `~/Library/LaunchAgents/com.ollama.app.plist` or similar).
2. Add a `<key>EnvironmentVariables</key>` section with your model path:
   ```xml
   <dict>
     <key>OLLAMA_MODELS</key>
     <string>/Volumes/MyDisk/ollama_models</string>
   </dict>
   ```
3. Reload: `launchctl unload ~/Library/LaunchAgents/com.ollama.app.plist && launchctl load ~/Library/LaunchAgents/com.ollama.app.plist`

This removes the symlink indirection but does **not** fix exFAT incompatibility. If the target path is still on exFAT, you still see the "corrupt manifest" warnings.

### Formatting external storage

If your internal disk is space-constrained (e.g., 89% full, necessitating external storage for any large models), reformat the external volume as APFS:

1. Backup the entire drive first.
2. Use Disk Utility or `diskutil secureErase APFS ...` to reformat.
3. Restore model files from backup.

This fixes the xattr incompatibility regardless of which runner manages the path — Ollama, LM Studio, or any other tool. It does **not** solve symlink-based mount-timing issues if you're still using a symlink.

## mlx-lm's different setup

[mlx-lm](https://github.com/ml-explore/mlx-lm) uses the standard Hugging Face cache (`~/.cache/huggingface`, overridable via `HF_HOME`) with no daemon and no model-storage-location conventions. On the default setup (internal disk cache), it sidesteps both failure modes.

**However**, if `HF_HOME` itself gets redirected to external storage (`export HF_HOME=/Volumes/...`), the same filesystem-format lesson applies: if that path is on exFAT, tools that manage the cache can generate AppleDouble files and encounter load failures. The fix is the same — use APFS, not exFAT.

## Runner tradeoffs (context)

| Runner | Daemon | HTTP API | Model storage | When to use |
|--------|--------|----------|----------------|------------|
| Ollama | Yes (background process) | Yes (`:11434`) | Tool-specific (`OLLAMA_MODELS`) | Broad IDE/tool integration; can isolate process from code |
| LM Studio | Yes (desktop GUI) | Yes | Tool-specific | Interactive exploration; heavier resource footprint; GUI workflows |
| mlx-lm | No (in-process library) | No | Standard HF cache (`HF_HOME`) | Lightweight, no persistent process; caller manages model lifecycle |

Choose based on integration needs, not storage convenience. If integration favors a daemon but your internal disk is space-constrained, the fix is the external volume's filesystem, not avoiding external storage.
