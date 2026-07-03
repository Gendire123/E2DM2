import sys
import re
import hashlib
from pathlib import Path

def get_sha256(filepath):
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()

def main():
    if len(sys.argv) < 3:
        print("Usage: update_website.py <version> <installer_path>")
        sys.exit(1)
        
    version = sys.argv[1]
    installer_path = Path(sys.argv[2])
    
    if not installer_path.exists():
        print(f"Installer path not found: {installer_path}")
        sys.exit(1)
        
    # Calculate hash and size
    file_hash = get_sha256(installer_path).lower()
    file_size_mb = f"{installer_path.stat().st_size / (1024 * 1024):.1f} MB"
    
    # Locate website index.html
    # Drone root is sibling to E2DM2 Website
    project_root = Path(__file__).parent.parent
    website_dir = project_root.parent / "E2DM2 Website"
    index_html_path = website_dir / "index.html"
    
    if not index_html_path.exists():
        print(f"Website index.html not found at: {index_html_path}")
        # Exit gracefully so it doesn't break compiling if the website folder is moved/missing
        sys.exit(0)
        
    content = index_html_path.read_text(encoding='utf-8')
    
    # Replace download link
    # href="https://github.com/Gendire123/E2DM2-Releases/releases/download/v1.0.3/E2DM2-Setup-1.0.3.exe"
    content = re.sub(
        r'href="https://github\.com/Gendire123/E2DM2-Releases/releases/download/v[^/]+/E2DM2-Setup-[^"]+\.exe"',
        f'href="https://github.com/Gendire123/E2DM2-Releases/releases/download/v{version}/E2DM2-Setup-{version}.exe"',
        content
    )
    
    # Replace data-umami-event-version
    # data-umami-event-version="v1.0.3"
    content = re.sub(
        r'data-umami-event-version="v[^"]+"',
        f'data-umami-event-version="v{version}"',
        content
    )
    
    # Replace download note label
    # Version 1.0.3 • Windows (64-bit)
    content = re.sub(
        r'Version [^•\s]+ • Windows \(64-bit\)',
        f'Version {version} • Windows (64-bit)',
        content
    )
    
    # Replace trust version metadata
    # <span class="metadata-value" data-trust-version>1.0.3</span>
    content = re.sub(
        r'(data-trust-version>)[^<]+(<)',
        rf'\g<1>{version}\g<2>',
        content
    )
    
    # Replace trust size metadata
    # <span class="metadata-value" data-trust-size>425.2 MB</span>
    content = re.sub(
        r'(data-trust-size>)[^<]+(<)',
        rf'\g<1>{file_size_mb}\g<2>',
        content
    )
    
    # Replace VirusTotal URL
    # https://www.virustotal.com/gui/file/ec3d8b129454a893356fda154314c6af8906cc1114f2d5fb0f0b37a11c3c4f9f
    content = re.sub(
        r'href="https://www\.virustotal\.com/gui/file/[0-9a-fA-F]+"',
        f'href="https://www.virustotal.com/gui/file/{file_hash}"',
        content
    )
    
    # Replace displayed hash
    # <code class="hash-text" id="hash-val">ec3d8b129454a893356fda154314c6af8906cc1114f2d5fb0f0b37a11c3c4f9f</code>
    content = re.sub(
        r'(id="hash-val">)[0-9a-fA-F]+(<)',
        rf'\g<1>{file_hash}\g<2>',
        content
    )
    
    index_html_path.write_text(content, encoding='utf-8')
    print(f"Successfully updated website index.html for version {version} (Hash: {file_hash}, Size: {file_size_mb})")

if __name__ == '__main__':
    main()
