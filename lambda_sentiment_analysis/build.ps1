# This script prepares the Lambda deployment package using a robust virtual environment.
$ErrorActionPreference = "Stop"

# 1. Define paths
$SourcePath = $PSScriptRoot
$VenvPath = Join-Path -Path $SourcePath -ChildPath ".venv"
$PackagePath = Join-Path -Path $SourcePath -ChildPath "package"

# 2. Clean up previous build artifacts
Write-Host "Cleaning up previous build artifacts..."
if (Test-Path $PackagePath) { Remove-Item -Recurse -Force $PackagePath }
if (Test-Path $VenvPath) { Remove-Item -Recurse -Force $VenvPath }
New-Item -ItemType Directory -Path $PackagePath

# 3. Create and activate a virtual environment
Write-Host "Creating Python virtual environment..."
py -m venv $VenvPath
. (Join-Path -Path $VenvPath -ChildPath "Scripts\Activate.ps1")
Write-Host "Virtual environment activated."

# 4. Install dependencies from requirements.txt into the package directory for the correct platform
Write-Host "Installing dependencies for Linux (manylinux2014_x86_64)..."
pip install --target $PackagePath -r (Join-Path -Path $SourcePath -ChildPath "requirements.txt") --platform manylinux2014_x86_64 --python-version 3.9 --only-binary=:all:
Write-Host "Dependencies installed successfully."

# 5. Copy the Lambda handler code into the package directory
Write-Host "Copying Lambda handler code..."
Copy-Item -Path (Join-Path -Path $SourcePath -ChildPath "main.py") -Destination $PackagePath
Write-Host "Lambda handler copied successfully."

# 6. Deactivate and clean up the virtual environment
Write-Host "Deactivating and cleaning up virtual environment..."
Deactivate
Remove-Item -Recurse -Force $VenvPath
Write-Host "Build complete. Lambda package created at: $PackagePath"