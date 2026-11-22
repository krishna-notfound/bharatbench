"""Import a release APK from a public (or token-accessible) GitHub repository.

Only the GitHub REST API and the release asset download are used; nothing is built from source and
nothing from the repository is executed on the API host.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import anyio
import httpx

MAX_APK_BYTES = 200 * 1024 * 1024
API = "https://api.github.com"
CHUNK = 1024 * 1024
NO_APK_MESSAGE = (
    "This repo has no APK in its releases. Upload the APK, or add one to a GitHub release."
)
BAD_URL = "That isn't a GitHub repository link. Use https://github.com/owner/repo"
_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
MAX_REDIRECTS = 4
_ALLOWED_HOST_SUFFIXES = ("github.com", "githubusercontent.com")
_PREFER = ("universal", "arm64", "x86_64")


class GithubImportError(Exception):
    """A user-facing import failure carrying an HTTP status."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass(frozen=True)
class RepoRef:
    owner: str
    repo: str
    tag: str | None = None


@dataclass(frozen=True)
class ApkAsset:
    name: str
    url: str  # API asset url (works with a token for private repos)
    size: int
    release: str  # tag or release name for the log line


def parse_repo_url(raw: str) -> RepoRef:
    text = (raw or "").strip()
    if text and "://" not in text and text.lower().startswith(("github.com/", "www.github.com/")):
        text = "https://" + text
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or host not in ("github.com", "www.github.com"):
        raise GithubImportError(400, BAD_URL)
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        raise GithubImportError(400, BAD_URL)
    owner, repo = parts[0], parts[1].removesuffix(".git")
    if not _NAME.match(owner) or not _NAME.match(repo) or repo in (".", ".."):
        raise GithubImportError(400, BAD_URL)
    tag = None
    if len(parts) >= 5 and parts[2] == "releases" and parts[3] == "tag":
        tag = "/".join(parts[4:])
        if any(seg in ("", ".", "..") or "%" in seg or "\\" in seg for seg in tag.split("/")):
            raise GithubImportError(400, BAD_URL)
    return RepoRef(owner, repo, tag)


def _score(name: str) -> int:
    low = name.lower()
    for i, key in enumerate(_PREFER):
        if key in low:
            return len(_PREFER) - i
    return 0


def pick_apk(release: dict) -> dict | None:
    """Best .apk asset of a release (never .aab); prefers universal, then arm64, then x86_64 names."""
    apks = [
        a
        for a in release.get("assets") or []
        if str(a.get("name", "")).lower().endswith(".apk") and a.get("state", "uploaded") == "uploaded"
    ]
    if not apks:
        return None
    return min(apks, key=lambda a: -_score(str(a["name"])))  # first minimal: upload order breaks ties


def _headers(token: str | None, *, accept: str = "application/vnd.github+json") -> dict[str, str]:
    h = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "BharatBench"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def _api_error(resp: httpx.Response, ref: RepoRef, token: str | None) -> GithubImportError:
    if resp.status_code == 404:
        hint = "" if token else " If it is private, the server needs a GITHUB_TOKEN."
        return GithubImportError(404, f"I couldn't find {ref.owner}/{ref.repo}, or it is private.{hint}")
    if resp.status_code in (401, 403, 429):
        if resp.headers.get("x-ratelimit-remaining") == "0" or resp.status_code == 429:
            return GithubImportError(429, "GitHub is rate-limiting this server right now. Try again in a few minutes.")
        return GithubImportError(403, f"GitHub refused access to {ref.owner}/{ref.repo}.")
    return GithubImportError(502, f"GitHub returned an unexpected error ({resp.status_code}).")


async def find_apk(ref: RepoRef, token: str | None, client: httpx.AsyncClient) -> ApkAsset:
    base = f"{API}/repos/{ref.owner}/{ref.repo}/releases"
    h = _headers(token)
    release: dict | None = None
    asset: dict | None = None
    if ref.tag:
        resp = await client.get(f"{base}/tags/{quote(ref.tag, safe='')}", headers=h)
        if resp.status_code == 404:
            raise GithubImportError(404, f"I couldn't find release {ref.tag} in {ref.owner}/{ref.repo}.")
        if resp.status_code != 200:
            raise _api_error(resp, ref, token)
        release = resp.json()
        asset = pick_apk(release)
    else:
        resp = await client.get(f"{base}/latest", headers=h)
        if resp.status_code == 200:
            release = resp.json()
            asset = pick_apk(release)
        elif resp.status_code != 404:
            raise _api_error(resp, ref, token)
        if asset is None:
            lst = await client.get(base, headers=h, params={"per_page": 30})
            if lst.status_code != 200:
                raise _api_error(lst, ref, token)
            releases = [r for r in lst.json() if not r.get("draft")]
            if not releases and release is None:
                raise GithubImportError(404, "This repo has no releases yet. " + NO_APK_MESSAGE)
            for r in releases:
                asset = pick_apk(r)
                if asset:
                    release = r
                    break
    if asset is None or release is None:
        raise GithubImportError(404, NO_APK_MESSAGE)
    if int(asset.get("size") or 0) > MAX_APK_BYTES:
        raise GithubImportError(413, "The APK in that release is over the 200 MB limit.")
    label = release.get("tag_name") or release.get("name") or "release"
    return ApkAsset(str(asset["name"]), str(asset["url"]), int(asset.get("size") or 0), str(label))


def _github_host(url: str) -> bool:
    p = urlparse(url)
    host = (p.hostname or "").lower()
    return p.scheme == "https" and any(host == s or host.endswith("." + s) for s in _ALLOWED_HOST_SUFFIXES)


async def download_apk(asset: ApkAsset, dest: Path, token: str | None, client: httpx.AsyncClient) -> int:
    """Stream the asset to `dest`, enforcing the size cap while reading and checking the ZIP magic."""
    size = 0
    try:
        # Follow redirects by hand: every hop must stay on GitHub hosts over https (no SSRF to internal
        # addresses such as 169.254.169.254), and the token is only ever sent to api.github.com.
        url = asset.url
        if not url.startswith(API + "/"):
            raise GithubImportError(502, "GitHub returned an unexpected download address.")
        for _hop in range(MAX_REDIRECTS + 1):
            h = _headers(token if url.startswith(API + "/") else None, accept="application/octet-stream")
            req = client.build_request("GET", url, headers=h)
            resp = await client.send(req, stream=True, follow_redirects=False)
            if resp.status_code in (301, 302, 303, 307, 308):
                nxt = urljoin(url, resp.headers.get("location", ""))
                await resp.aclose()
                if not _github_host(nxt):
                    raise GithubImportError(502, "GitHub redirected the download somewhere unexpected.")
                url = nxt
                continue
            break
        else:
            raise GithubImportError(502, "GitHub redirected the download too many times.")
        try:
            if resp.status_code != 200:
                raise GithubImportError(502, f"GitHub would not let me download the APK ({resp.status_code}).")
            async with await anyio.open_file(dest, "wb") as out:
                async for chunk in resp.aiter_bytes(CHUNK):
                    if size == 0 and not chunk.startswith(b"PK"):
                        raise GithubImportError(400, "The release file is not a valid APK (not a ZIP archive).")
                    size += len(chunk)
                    if size > MAX_APK_BYTES:
                        raise GithubImportError(413, "The APK in that release is over the 200 MB limit.")
                    await out.write(chunk)
        finally:
            await resp.aclose()
    except httpx.HTTPError as e:
        raise GithubImportError(504, f"Downloading the APK from GitHub failed ({type(e).__name__}). Try again.") from e
    if size == 0:
        raise GithubImportError(400, "The release file is empty.")
    return size


def new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=60.0))
