curl -H "Authorization: token YOUR_GITHUB_TOKEN" \
     -H "Accept: application/vnd.github.v3+json" \
     "https://api.github.com/repos/ORG_NAME/REPO_NAME/commits?path=.checkmarx/application.yml&sha=main&per_page=100" | jq
