# Build script for data labeling Lambda function

Write-Host "Building data labeling Lambda package..."

# Remove existing package directory
if (Test-Path "package") {
    Remove-Item -Recurse -Force package
}

# Create package directory
New-Item -ItemType Directory -Path package

# Copy main.py to package directory
Copy-Item main_s3_direct.py package/main.py

# Install dependencies
if (Test-Path "requirements.txt") {
    Write-Host "Installing Python dependencies..."
    pip install -r requirements.txt -t package/
}

Write-Host "Data labeling Lambda package built successfully!"
Write-Host "Package contents:"
Get-ChildItem package/