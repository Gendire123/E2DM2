import os
import sys
import json
import urllib.request
import urllib.error
from pathlib import Path

def upload_file_to_virustotal(filepath: str, api_key: str) -> bool:
    filepath_path = Path(filepath)
    if not filepath_path.exists():
        print(f"File not found: {filepath_path}")
        return False

    print("Requesting large file upload URL from VirusTotal...")
    url = "https://www.virustotal.com/api/v3/files/upload_url"
    req = urllib.request.Request(
        url,
        headers={
            "x-apikey": api_key,
            "Accept": "application/json",
            "User-Agent": "E2DM2-BuildAutomation"
        },
        method="GET"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            upload_url = res_data.get("data")
            if not upload_url:
                print("Error: Did not receive a valid upload URL from VirusTotal.")
                return False
    except Exception as e:
        print(f"Error fetching large file upload URL: {e}")
        return False

    print(f"Uploading {filepath_path.name} to VirusTotal...")
    print("Note: This upload is ~425MB and will take a few minutes depending on your internet upload speed.")

    boundary = "----VirusTotalUploadBoundary"
    filename = filepath_path.name
    
    header_part = (
        f"--{boundary}\r\n"
        f"Content-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8")
    
    footer_part = f"\r\n--{boundary}--\r\n".encode("utf-8")

    try:
        # Load file data into memory to compile multipart request
        with open(filepath_path, "rb") as f:
            file_data = f.read()
            
        body = header_part + file_data + footer_part
        
        post_req = urllib.request.Request(
            upload_url,
            data=body,
            headers={
                "x-apikey": api_key,
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
                "Accept": "application/json",
                "User-Agent": "E2DM2-BuildAutomation"
            },
            method="POST"
        )
        
        # VirusTotal upload takes time, set a generous timeout
        with urllib.request.urlopen(post_req, timeout=600) as response:
            res = json.loads(response.read().decode("utf-8"))
            analysis_id = res.get("data", {}).get("id")
            print(f"Upload complete! VirusTotal analysis started successfully (Analysis ID: {analysis_id})")
            return True
            
    except Exception as e:
        print(f"Error uploading file: {e}")
        return False

def main():
    if len(sys.argv) < 2:
        print("Usage: upload_virustotal.py <installer_path>")
        sys.exit(1)
        
    installer_path = sys.argv[1]
    
    api_key = os.environ.get("VIRUSTOTAL_API_KEY")
    if not api_key:
        print("Error: VIRUSTOTAL_API_KEY environment variable is not set.")
        sys.exit(1)
        
    success = upload_file_to_virustotal(installer_path, api_key)
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()
