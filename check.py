import requests
import subprocess
import os

# Configuration
GITHUB_TOKEN = 'your_github_token'
ORG_NAME = 'your_organization_name'
REPO_NAMES = ['repo1', 'repo2', 'repo3']  # List of repositories to audit
AUDIT_LOG = '/tmp/audit_log_test.txt'  # Use an absolute path to avoid any relative path issues

headers = {
    'Authorization': f'token {GITHUB_TOKEN}',
    'Accept': 'application/vnd.github.v3+json'
}

# Function to get pull requests for a repository
def get_pull_requests(repo):
    url = f'https://api.github.com/repos/{ORG_NAME}/{repo}/pulls?state=all&per_page=100'
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json()
    else:
        print(f'Failed to fetch pull requests for {repo}: {response.status_code}')
        return []

# Function to get files changed in a pull request
def get_pull_request_files(repo, pr_number):
    url = f'https://api.github.com/repos/{ORG_NAME}/{repo}/pulls/{pr_number}/files'
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json()
    else:
        print(f'Failed to fetch files for PR #{pr_number} in {repo}: {response.status_code}')
        return []

# Function to audit changes to files in .checkmarx directory in a repository
def audit_repository(repo):
    prs = get_pull_requests(repo)
    for pr in prs:
        files = get_pull_request_files(repo, pr['number'])
        for file in files:
            if file['filename'].startswith('.checkmarx/'):
                try:
                    with open(AUDIT_LOG, 'a') as log_file:
                        log_file.write(f'Repository: {repo}\n')
                        log_file.write(f'Pull Request: #{pr["number"]} - {pr["title"]}\n')
                        log_file.write(f'Author: {pr["user"]["login"]}\n')
                        log_file.write(f'Date: {pr["created_at"]}\n')
                        log_file.write(f'File: {file["filename"]} (Additions: {file["additions"]}, Deletions: {file["deletions"]})\n')
                        log_file.write('\n')
                except Exception as e:
                    print(f"Failed to write to log file {AUDIT_LOG}: {e}")

# Main execution
if __name__ == '__main__':
    if os.path.exists(AUDIT_LOG):
        os.remove(AUDIT_LOG)
        print(f"Existing audit log {AUDIT_LOG} removed.")

    for repo in REPO_NAMES:
        audit_repository(repo)
    
    if os.path.exists(AUDIT_LOG):
        print(f'Audit completed. Check {AUDIT_LOG} for details.')
    else:
        print(f"Audit log {AUDIT_LOG} was not created.")
