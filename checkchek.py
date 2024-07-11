import requests
from datetime import datetime
import subprocess
import os

# Configuration
GITHUB_TOKEN = 'your_github_token'
ORG_NAME = 'your_organization_name'
REPO_NAME = 'your_test_repository'  # Specify the repository name for testing
AUDIT_LOG = 'audit_log.txt'

# Function to audit changes to files in .checkmarx directory in a repository
def audit_repository(repo):
    repo_dir = f'/tmp/{repo}'
    if os.path.exists(repo_dir):
        subprocess.run(['rm', '-rf', repo_dir])
    subprocess.run(['git', 'clone', f'https://github.com/{ORG_NAME}/{repo}.git', repo_dir])
    os.chdir(repo_dir)
    result = subprocess.run(['git', 'log', '--pretty=format:%H %an %ad', '--date=iso', '--', '.checkmarx/'], capture_output=True, text=True)
    changes = result.stdout.strip().split('\n')
    if changes:
        with open(AUDIT_LOG, 'a') as log_file:
            log_file.write(f'Changes in {repo}:\n')
            for change in changes:
                log_file.write(f'{change}\n')
            log_file.write('\n')
    os.chdir('/tmp')

# Main execution
if __name__ == '__main__':
    audit_repository(REPO_NAME)
    print(f'Audit completed for {REPO_NAME}. Check {AUDIT_LOG} for details.')
