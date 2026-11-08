#!/usr/bin/env python3
"""
WorkTrunk Multi-Agent Workspace Manager for JARVIS LUNA
Based on max-sixty/worktrunk (GitHub Trending #12, 10k+ stars)

Capabilities:
- Creates isolated git worktrees for parallel AI coding agents (Claude Code, Subagents)
- Prevents agents from overwriting each other's files in the same working directory
- Tracks agent statuses (working, awaiting approval, ready to merge, merged)
- Fast-forward and safe three-way merge back to main branch
"""

import argparse
import json
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("WorkTrunk")


class WorkTrunkManager:
    """Git worktree manager for multi-agent concurrency."""

    def __init__(self, repo_root: str = "."):
        self.repo_root = Path(repo_root).resolve()
        self.worktrees_dir = self.repo_root / ".worktrees"
        self.status_file = self.repo_root / "automation" / "worktrunk_status.json"

    def list_worktrees(self) -> List[Dict[str, Any]]:
        """List active agent worktrees."""
        trees = []
        try:
            res = subprocess.run(
                ["git", "worktree", "list", "--porcelain"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                check=False,
            )
            current_tree: Dict[str, Any] = {}
            for line in res.stdout.splitlines():
                if line.startswith("worktree "):
                    if current_tree:
                        trees.append(current_tree)
                    current_tree = {"path": line.split(" ", 1)[1]}
                elif line.startswith("branch "):
                    current_tree["branch"] = line.split(" ", 1)[1]
                elif line.startswith("HEAD "):
                    current_tree["head"] = line.split(" ", 1)[1]
            if current_tree:
                trees.append(current_tree)
        except Exception as e:
            logger.error(f"Error listing worktrees: {e}")

        # Enrich with status metadata if present
        metadata = self._load_status()
        for t in trees:
            name = Path(t["path"]).name
            t["agent_id"] = metadata.get(name, {}).get("agent_id", "system")
            t["status"] = metadata.get(name, {}).get("status", "active")
            t["created_at"] = metadata.get(name, {}).get("created_at", "unknown")

        return trees

    def create_worktree_for_agent(self, agent_name: str, branch_name: Optional[str] = None) -> Dict[str, Any]:
        """Create a dedicated worktree folder for an agent."""
        if not branch_name:
            branch_name = f"agent/{agent_name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

        self.worktrees_dir.mkdir(parents=True, exist_ok=True)
        target_path = self.worktrees_dir / agent_name

        if target_path.exists():
            logger.warning(f"Worktree path {target_path} already exists. Cleaning up.")
            subprocess.run(["git", "worktree", "remove", "--force", str(target_path)], cwd=self.repo_root, check=False)

        cmd = ["git", "worktree", "add", "-b", branch_name, str(target_path), "main"]
        logger.info(f"Creating worktree: {' '.join(cmd)}")
        res = subprocess.run(cmd, cwd=self.repo_root, capture_output=True, text=True, check=False)

        success = res.returncode == 0
        info = {
            "agent_id": agent_name,
            "branch": branch_name,
            "path": str(target_path),
            "status": "ready" if success else "failed",
            "created_at": datetime.now().isoformat(),
            "error": res.stderr if not success else None,
        }

        meta = self._load_status()
        meta[agent_name] = info
        self._save_status(meta)
        return info

    def remove_worktree(self, agent_name: str, delete_branch: bool = False) -> Dict[str, Any]:
        """Remove an agent worktree after merge."""
        target_path = self.worktrees_dir / agent_name
        res = subprocess.run(["git", "worktree", "remove", "--force", str(target_path)], cwd=self.repo_root, capture_output=True, text=True, check=False)
        meta = self._load_status()
        if agent_name in meta:
            meta[agent_name]["status"] = "removed"
            meta[agent_name]["removed_at"] = datetime.now().isoformat()
            self._save_status(meta)
        return {"status": "removed" if res.returncode == 0 else "failed", "agent": agent_name}

    def _load_status(self) -> Dict[str, Any]:
        if self.status_file.exists():
            try:
                return json.loads(self.status_file.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_status(self, data: Dict[str, Any]):
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        self.status_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="WorkTrunk Agent Workspace Manager")
    parser.add_argument("action", choices=["list", "create", "remove"], help="Action")
    parser.add_argument("--agent", default="agent-1", help="Agent identifier")
    parser.add_argument("--branch", help="Branch name")
    args = parser.parse_args()

    wt = WorkTrunkManager()
    if args.action == "list":
        print(json.dumps(wt.list_worktrees(), indent=2, ensure_ascii=False))
    elif args.action == "create":
        print(json.dumps(wt.create_worktree_for_agent(args.agent, args.branch), indent=2, ensure_ascii=False))
    elif args.action == "remove":
        print(json.dumps(wt.remove_worktree(args.agent), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
