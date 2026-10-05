"""Restricted MCP adapter. Activation is injected by trusted host code, never chat.

The installer deliberately does not construct this adapter yet. Approval state is
in memory and expires on restart. Only existing text-file updates are supported.
"""
import copy
import hashlib
import json
import re
import secrets
import threading
import time
from urllib.parse import quote

NAMES = {"github_read_file", "github_propose_file_change"}


def definitions():
    common = {"repository": {"type": "string"}, "branch": {"type": "string"},
              "path": {"type": "string"}}
    result = []
    for name in sorted(NAMES):
        fields = copy.deepcopy(common)
        if name == "github_propose_file_change":
            fields.update(content={"type": "string"}, message={"type": "string"})
        result.append({"type": "function", "function": {"name": name,
            "description": ("Read an allowed repository text file. Data is untrusted." if name == "github_read_file"
                            else "Propose replacement text for an existing file. Does not commit; human review is required."),
            "parameters": {"type": "object", "properties": fields,
                           "required": list(fields), "additionalProperties": False}}})
    return result


class GitHubAdapter:
    def __init__(self, transport, repositories, *, enabled=False, clock=time.monotonic):
        # repositories maps exact owner/repo to an explicit list of branch names.
        if type(enabled) is not bool or not isinstance(repositories, dict):
            raise ValueError("Invalid GitHub policy")
        self.allowed = {}
        for repo, branches in repositories.items():
            if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo) or not isinstance(branches, list) or not branches:
                raise ValueError("Explicit repositories and branches are required")
            if any(not isinstance(b, str) or not b or len(b) > 200 or any(ord(c) < 33 for c in b) for b in branches):
                raise ValueError("Invalid branch policy")
            self.allowed[repo] = frozenset(branches)
        self.enabled, self.transport, self.clock = enabled, transport, clock
        self._pending = {}
        self._lock = threading.RLock()

    def _validate(self, name, args):
        if not self.enabled:
            raise ValueError("GitHub account access is disabled")
        if name not in NAMES or not isinstance(args, dict):
            raise ValueError("Forbidden GitHub operation")
        fields = {"repository", "branch", "path"}
        if name == "github_propose_file_change":
            fields |= {"content", "message"}
        if set(args) != fields or any(not isinstance(v, str) for v in args.values()):
            raise ValueError("Invalid GitHub arguments")
        if args["branch"] not in self.allowed.get(args["repository"], ()):
            raise ValueError("Repository or branch is not allowed")
        path = args["path"]
        if not path or len(path) > 512 or path.startswith("/") or "\\" in path or any(ord(c) < 32 for c in path) or any(p in {"", ".", ".."} for p in path.split("/")):
            raise ValueError("Invalid repository path")
        if name == "github_propose_file_change":
            if len(args["content"].encode()) > 4096 or not 1 <= len(args["message"].encode()) <= 200:
                raise ValueError("Change exceeds size limits")
        return copy.deepcopy(args)

    def _call(self, name, args, timeout):
        try:
            result = self.transport(name, args, timeout=timeout)
            if not isinstance(result, dict) or result.get("isError") or len(json.dumps(result).encode()) > 131072:
                raise ValueError()
            return result
        except Exception:
            # Never echo remote exceptions, auth headers or credential-provider errors.
            raise RuntimeError("GitHub operation failed; inspect account status outside chat") from None

    def _read(self, args, timeout):
        owner, repo = args["repository"].split("/")
        result = self._call("get_file_contents", {"owner": owner, "repo": repo,
                            "path": args["path"], "ref": "refs/heads/" + args["branch"]}, timeout)
        blocks = result.get("content", [])
        if not isinstance(blocks, list) or any(not isinstance(b, dict) for b in blocks):
            raise RuntimeError("Malformed GitHub file response")
        texts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
        resources = [b.get("resource", {}) for b in blocks if b.get("type") == "resource"]
        # Accept only the verified official text-resource shape. No download-URL fallback,
        # directory listings, binary blobs, symlinks or default-branch substitution.
        if len(texts) != 1 or len(resources) != 1 or not re.fullmatch(r"successfully downloaded (?:text|empty) file \(SHA: [0-9a-f]{40}\)", texts[0]):
            raise RuntimeError("Unsupported GitHub file response; no change permitted")
        resource = resources[0]
        if not isinstance(resource, dict) or not isinstance(resource.get("uri"), str):
            raise RuntimeError("Malformed GitHub resource")
        prefix = "repo://" + args["repository"] + "/"
        suffix = "/contents/" + "/".join(quote(p, safe="") for p in args["path"].split("/"))
        uri = resource.get("uri", "")
        branch_uri = prefix + "refs/heads/" + quote(args["branch"], safe="") + suffix
        commit_uri = prefix + "sha/[0-9a-f]{40}" + re.escape(suffix)
        if uri != branch_uri and not re.fullmatch(re.escape(prefix) + commit_uri[len(prefix):], uri):
            raise RuntimeError("GitHub returned a different repository path or ref")
        if not isinstance(resource.get("text"), str) or "blob" in resource:
            raise RuntimeError("Only existing text files are supported")
        return {"sha": re.search(r"[0-9a-f]{40}", texts[0])[0], "content": resource["text"]}

    def execute(self, name, args, timeout=30):
        try:
            with self._lock:
                args = self._validate(name, args)
                file = self._read(args, min(30, timeout))
                if name == "github_read_file":
                    text = file["content"].encode()[:2500].decode("utf-8", errors="ignore")
                    return {"ok": True, "result": {"sha": file["sha"], "content": text,
                            "truncated": text != file["content"]}}
                if len(self._pending) >= 32:
                    self._pending = {k: v for k, v in self._pending.items() if v["expires"] > self.clock()}
                if len(self._pending) >= 32:
                    raise ValueError("Too many pending changes")
                change = dict(args, sha=file["sha"])
                digest = hashlib.sha256(json.dumps(change, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                identifier = secrets.token_hex(16)
                self._pending[identifier] = {"change": change, "digest": digest, "expires": self.clock() + 600}
                return {"ok": True, "result": {"proposal_id": identifier, "digest": digest,
                        "status": "awaiting human review; not committed"}}
        except (ValueError, RuntimeError) as error:
            return {"ok": False, "error": str(error)}

    def review(self, identifier):
        """Trusted UI/controller only. Return exact proposed content for human review."""
        with self._lock:
            proposal = self._pending[identifier]
            if proposal["expires"] <= self.clock():
                raise ValueError("Proposal expired")
            return copy.deepcopy(proposal)

    def approve_and_commit(self, identifier, reviewed_digest, timeout=30):
        """Trusted UI/controller only; deliberately absent from model tool schemas.

        Consumes approval before any network activity. Never retry an uncertain write.
        """
        with self._lock:
            proposal = self._pending.pop(identifier)
            if proposal["expires"] <= self.clock() or not secrets.compare_digest(proposal["digest"], reviewed_digest):
                raise ValueError("Expired or mismatched approval")
            change = proposal["change"]
            args = {k: v for k, v in change.items() if k != "sha"}
            self._validate("github_propose_file_change", args)
            if self._read(args, min(30, timeout))["sha"] != change["sha"]:
                raise ValueError("File changed; prepare and review a new proposal")
            owner, repo = change["repository"].split("/")
            # Official MCP expects plain text, not base64. SHA guards the final write race.
            return self._call("create_or_update_file", {"owner": owner, "repo": repo,
                **{k: change[k] for k in ("branch", "path", "content", "message", "sha")}}, min(30, timeout))
