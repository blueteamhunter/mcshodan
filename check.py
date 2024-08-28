import boto3

def list_hosted_zones():
    """List all hosted zones in Route 53."""
    client = boto3.client('route53')
    response = client.list_hosted_zones()
    hosted_zones = response['HostedZones']
    
    return hosted_zones

def list_dns_records(hosted_zone_id):
    """List all DNS records in a given hosted zone."""
    client = boto3.client('route53')
    paginator = client.get_paginator('list_resource_record_sets')
    records = []
    
    for page in paginator.paginate(HostedZoneId=hosted_zone_id):
        records.extend(page['ResourceRecordSets'])
    
    return records

def validate_dns_record(record):
    """Validate a DNS record for security best practices."""
    if record['Type'] == 'A':
        # Example: Check for public IPs in internal zones
        for r in record['ResourceRecords']:
            ip = r['Value']
            if ip.startswith('192.') or ip.startswith('10.'):
                print(f"Potential misconfiguration: {record['Name']} points to private IP.")
    
    if record['Type'] == 'CNAME':
        # Check for unwanted redirections
        if record['ResourceRecords'][0]['Value'].endswith('.internal'):
            print(f"Misconfiguration: {record['Name']} points to internal CNAME.")
    
    # Example: Detect wildcard records
    if record['Name'].startswith('*'):
        print(f"Warning: Wildcard record detected -> {record['Name']}")
    
    # Add more validation rules as needed

def sanitize_dns_entries():
    """Sanitize DNS entries in all hosted zones."""
    hosted_zones = list_hosted_zones()
    
    for zone in hosted_zones:
        print(f"Checking zone: {zone['Name']}")
        records = list_dns_records(zone['Id'])
        
        for record in records:
            validate_dns_record(record)
            # Add logic to remove or fix the record if needed

if __name__ == "__main__":
    sanitize_dns_entries()
