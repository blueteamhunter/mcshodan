import requests

# Configuration
GITHUB_TOKEN = 'your_generated_github_token'
ORG_NAME = 'your_organization_name'
REPO_NAME = 'your_test_repository'  # Enter the repository you want to test
AUDIT_LOG = 'audit_log_test.txt'
SEARCH_FILE = '.checkmarx/application.yml'

headers = {
    'Authorization': f'token {GITHUB_TOKEN}',
    'Accept': 'application/vnd.github.v3+json'
}

# Function to audit changes to application.yml in a repository
def audit_repository(repo):
    repo_url = f'https://api.github.com/repos/{ORG_NAME}/{repo}/commits'
    params = {'path': SEARCH_FILE, 'per_page': 100}
    repo_audit_log = []

    while repo_url:
        response = requests.get(repo_url, headers=headers, params=params)
        if response.status_code == 200:
            commits = response.json()
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
            repo_url = response.links.get('next', {}).get('url')
        else:
            print(f'Error: {response.status_code} - {response.text}')
            break
    
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
    results = audit_repository(REPO_NAME)
    write_audit_log(results)
    print(f'Audit completed for {REPO_NAME}. Check {AUDIT_LOG} for details.')
