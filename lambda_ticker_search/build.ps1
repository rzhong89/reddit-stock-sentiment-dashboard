# Build script for Lambda ticker search function
Write-Host "Building Lambda ticker search package..."

# Remove existing package directory
if (Test-Path "package") {
    Remove-Item -Recurse -Force "package"
}

# Create package directory
New-Item -ItemType Directory -Name "package"

# Copy main.py to package directory
Copy-Item "main.py" "package/"

# Install dependencies
pip install -r requirements.txt -t package/

Write-Host "Package built successfully!"
Write-Host "Files in package directory:"
Get-ChildItem package/ -Recurse -Name | Select-Object -First 20