import requests

# Configuration
GITHUB_TOKEN = 'your_generated_github_token'
ORG_NAME = 'your_organization_name'
REPO_NAME = 'your_test_repository'  # For testing purposes, specify a single repository
SEARCH_FILE = '.checkmarx/application.yml'
AUDIT_LOG = 'audit_log_test.txt'
BRANCH_NAME = 'main'  # The branch you want to query, e.g., 'main' or 'master'

headers = {
    'Authorization': f'token {GITHUB_TOKEN}',
    'Accept': 'application/vnd.github.v3+json'
}

# Function to get the commit history of a repository's main branch
def get_commit_history(repo, branch):
    url = f'https://api.github.com/repos/{ORG_NAME}/{repo}/commits'
    params = {'path': SEARCH_FILE, 'sha': branch, 'per_page': 100}
    commits = []

    while url:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            commits.extend(response.json())
            url = response.links.get('next', {}).get('url')
        else:
            print(f'Error: {response.status_code} - {response.text}')
            break
    
    return commits

# Function to parse commit details for changes to application.yml
def parse_commit_details(repo, commits):
    repo_audit_log = []

    for commit in commits:
        commit_details = requests.get(commit['url'], headers=headers).json()
        for file in commit_details.get('files', []):
            if file['filename'] == SEARCH_FILE and 'previous_filename' in file:
                repo_audit_log.append({
                    'repo': repo,
                    'commit': commit['sha'],
                    'author': commit['commit']['author']['name'],
                    'date': commit['commit']['author']['date'],
                    'previous_filename': file['previous_filename']
                })
    
    return repo_audit_log

# Function to write audit logs to a file
def write_audit_log(results):
    with open(AUDIT_LOG, 'a') as log_file:
        for entry in results:
            log_file.write(f"Repository: {entry['repo']}\n")
            log_file.write(f"Commit: {entry['commit']}\n")
            log_file.write(f"Author: {entry['author']}\n")
            log_file.write(f"Date: {entry['date']}\n")
            log_file.write(f"Previous Filename: {entry['previous_filename']}\n")
            log_file.write('\n')

# Main execution
if __name__ == '__main__':
    commits = get_commit_history(REPO_NAME, BRANCH_NAME)
    results = parse_commit_details(REPO_NAME, commits)
    write_audit_log(results)
    print(f'Audit completed for {REPO_NAME} on branch {BRANCH_NAME}. Check {AUDIT_LOG} for details.')
