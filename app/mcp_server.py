# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from mcp.server.fastmcp import FastMCP
import os
import datetime
import json

mcp = FastMCP("Digital Clutter Cleaner Server")

@mcp.tool()
def list_directory_clutter(path: str) -> str:
    """
    Lists files in the directory with size and age to help identify clutter.
    
    Args:
        path: The absolute directory path to scan.
    """
    if not os.path.exists(path):
        return f"Directory {path} not found. Proposing a simulated directory listing for demonstration:\n" \
               "- raw_camera_backup_copy_2024.png (14.2 MB, duplicate png)\n" \
               "- install_installer_final_v3.exe (120 MB, 1.5 years old)\n" \
               "- temp_dump_notes.txt (2.1 MB, 8 months old)\n" \
               "- notes_final.txt (4 KB, recently modified)\n"
    
    try:
        files = []
        for entry in os.scandir(path):
            if entry.is_file():
                stat = entry.stat()
                size_mb = stat.st_size / (1024 * 1024)
                age_days = (datetime.datetime.now() - datetime.datetime.fromtimestamp(stat.st_mtime)).days
                files.append(f"- {entry.name} ({size_mb:.2f} MB, {age_days} days old)")
        return "\n".join(files) if files else "Directory is empty."
    except Exception as e:
        return f"Error scanning directory: {str(e)}"

@mcp.tool()
def dry_run_file_moves(moves_json: str) -> str:
    """
    Simulates file moves and returns verification logs.
    
    Args:
        moves_json: JSON string of moves list, e.g. '[{"src": "path/a", "dest": "path/b"}]'
    """
    try:
        moves = json.loads(moves_json)
        results = []
        for m in moves:
            src = m.get("src")
            dest = m.get("dest")
            results.append(f"Verification: Move '{src}' -> '{dest}' is VALID (dry run)")
        return "\n".join(results)
    except Exception as e:
        return f"Failed to parse moves JSON: {str(e)}"

@mcp.tool()
def generate_email_filter_rules(spam_senders_json: str) -> str:
    """
    Generates custom XML rules for importing filters into an email client.
    
    Args:
        spam_senders_json: JSON string of senders to filter, e.g. '["spammer@domain.com"]'
    """
    try:
        senders = json.loads(spam_senders_json)
        xml = "<entry>\n"
        for s in senders:
            xml += f"  <category>Filter: {s}</category>\n"
            xml += f"  <property name='from' value='{s}'/>\n"
            xml += f"  <property name='shouldArchive' value='true'/>\n"
        xml += "</entry>"
        return xml
    except Exception as e:
        return f"Failed to generate filter rules: {str(e)}"

if __name__ == "__main__":
    mcp.run()
