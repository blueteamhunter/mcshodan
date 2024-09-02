import json

def read_and_sum_disk_usage(filename):
    total_disk_usage = 0

    # Open the file containing the output of the GitHub CLI command
    with open(filename, 'r') as file:
        # Read each line of the file
        for line in file:
            # Parse each line as JSON
            try:
                repo_data = json.loads(line.strip())
                # Add the disk usage value to the total
                total_disk_usage += repo_data.get('diskUsage', 0)
            except json.JSONDecodeError:
                print("Error decoding JSON from the line:", line)

    return total_disk_usage

# Usage example
if __name__ == "__main__":
    filename = 'gh_output.txt'  # Replace with your actual filename
    total_kilobytes = read_and_sum_disk_usage(filename)
    print("Total Disk Usage: {} Kilobytes".format(total_kilobytes))
