"""SSH helper for running commands and transferring files on a remote host.

Credentials are read from environment variables (never hardcode them):
  SSHX_HOST      target host (required)
  SSHX_USER      username   (default: root)
  SSHX_PASSWORD  password   (required)

Usage:
  SSHX_HOST=192.168.x.x SSHX_PASSWORD=... py -I tools/sshx.py run "command"
  SSHX_HOST=... SSHX_PASSWORD=... py -I tools/sshx.py put <local_path> <remote_path>
  SSHX_HOST=... SSHX_PASSWORD=... py -I tools/sshx.py get <remote_path> <local_path>

Requires: pip install paramiko
"""
import os
import sys
import paramiko

HOST = os.environ.get("SSHX_HOST")
USER = os.environ.get("SSHX_USER", "root")
PASSWORD = os.environ.get("SSHX_PASSWORD")


def main():
    if not HOST or not PASSWORD:
        print(__doc__)
        return 2
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    mode = sys.argv[1]

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=15,
                   allow_agent=False, look_for_keys=False)

    if mode == "run":
        stdin, stdout, stderr = client.exec_command(sys.argv[2], timeout=120)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        rc = stdout.channel.recv_exit_status()
        if out:
            print(out, end="" if out.endswith("\n") else "\n")
        if err:
            print("[stderr]", err, end="" if err.endswith("\n") else "\n")
        client.close()
        return rc

    if mode == "put":
        sftp = client.open_sftp()
        sftp.put(sys.argv[2], sys.argv[3])
        sftp.close()
        print(f"uploaded {sys.argv[2]} -> {sys.argv[3]}")
        client.close()
        return 0

    if mode == "get":
        sftp = client.open_sftp()
        sftp.get(sys.argv[2], sys.argv[3])
        sftp.close()
        print(f"downloaded {sys.argv[2]} -> {sys.argv[3]}")
        client.close()
        return 0

    print(f"unknown mode: {mode}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
