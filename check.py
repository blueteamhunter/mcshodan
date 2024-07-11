import requests
from datetime import datetime
import subprocess
import os

# Configuration
GITHUB_TOKEN = 'your_github_token'
ORG_NAME = 'your_organization_name'
REPO_NAME = 'your_test_repository'  # Specify the repository name for testing
AUDIT_LOG = 'audit_log_test.txt'

# Function to audit changes to files in .checkmarx directory in a repository
def audit_repository(repo):
    repo_dir = f'/tmp/{repo}'
    if os.path.exists(repo_dir):
        subprocess.run(['rm', '-rf', repo_dir])
    clone_result = subprocess.run(['git', 'clone', f'https://github.com/{ORG_NAME}/{repo}.git', repo_dir])
    
    if clone_result.returncode != 0:
        print(f"Failed to clone repository {repo}")
        return
    
    os.chdir(repo_dir)
    
    # Logging the current directory for debugging
    print(f"Changed directory to {repo_dir}")

    # Check for changes in the .checkmarx directory
    result = subprocess.run(['git', 'log', '--pretty=format:%H %an %ad %s', '--date=iso', '--', '.checkmarx/'], capture_output=True, text=True)
    changes = result.stdout.strip().split('\n')
    
    if result.returncode != 0:
        print(f"Failed to get git log for repository {repo}")
        return
    
    # Logging the changes for debugging
    print(f"Found changes: {changes}")

    if changes:
        try:
            with open(AUDIT_LOG, 'a') as log_file:
                log_file.write(f'Changes in {repo}:\n')
                for change in changes:
                    log_file.write(f'{change}\n')
                log_file.write('\n')
            print(f"Changes written to {AUDIT_LOG}")
        except Exception as e:
            print(f"Failed to write to log file {AUDIT_LOG}: {e}")
    else:
        print(f"No changes found in {repo} for .checkmarx directory")
    
    os.chdir('/tmp')

# Main execution
if __name__ == '__main__':
    audit_repository(REPO_NAME)
    print(f'Audit completed for {REPO_NAME}. Check {AUDIT_LOG} for details.')
