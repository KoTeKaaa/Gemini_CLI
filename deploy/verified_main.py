"""Read public GitHub metadata; deployment requires a verified dev -> main merge."""

import json
import re
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class GitHub:
    def __init__(self, repository: str):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
            raise ValueError('Invalid repository')
        self.base = 'https://api.github.com/repos/' + repository

    def get(self, path: str):
        request = Request(self.base + path, headers={'Accept': 'application/vnd.github+json',
                          'User-Agent': 'Gemini-CLI-deploy'})
        try:
            with urlopen(request, timeout=15) as response:
                data = response.read(4 * 1024 * 1024 + 1)
            if len(data) > 4 * 1024 * 1024:
                raise ValueError('GitHub response too large')
            return json.loads(data)
        except HTTPError as error:
            if error.code == 404:
                return None
            raise RuntimeError('GitHub metadata unavailable; installed release retained') from None


def verified_main(api: GitHub, repository: str, *, installed=None) -> str | None:
    branch = api.get('/git/ref/heads/main') or {}
    sha = branch.get('object', {}).get('sha', '')
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise ValueError('Cannot determine main revision')
    if sha == installed:
        return None
    runs = api.get('/actions/workflows/production.yml/runs?event=push&head_sha=' + sha + '&per_page=10') or {}
    candidates = [run for run in runs.get('workflow_runs', []) if run.get('head_sha') == sha
                  and run.get('event') == 'push' and run.get('head_branch') == 'main'
                  and run.get('repository', {}).get('full_name', '').casefold() == repository.casefold()]
    if not candidates:
        return None
    latest = max(candidates, key=lambda run: (run.get('run_number', 0), run.get('run_attempt', 1)))
    if latest.get('status') != 'completed' or latest.get('conclusion') != 'success':
        return None
    jobs = api.get(f'/actions/runs/{int(latest["id"])}/jobs?per_page=100') or {}
    if not any(job.get('name') == 'production-ready' and job.get('status') == 'completed'
               and job.get('conclusion') == 'success' for job in jobs.get('jobs', [])):
        return None
    pulls = api.get('/commits/' + sha + '/pulls?per_page=100') or []
    if not any(pull.get('merged_at') and pull.get('merge_commit_sha') == sha
               and pull.get('base', {}).get('ref') == 'main'
               and pull.get('head', {}).get('ref') == 'dev'
               and pull.get('head', {}).get('repo', {}).get('full_name', '').casefold() == repository.casefold()
               and pull.get('base', {}).get('repo', {}).get('full_name', '').casefold() == repository.casefold()
               for pull in pulls):
        return None
    # A newer main must never be overwritten by an older release after a long check.
    current = api.get('/git/ref/heads/main') or {}
    return sha if current.get('object', {}).get('sha') == sha else None
