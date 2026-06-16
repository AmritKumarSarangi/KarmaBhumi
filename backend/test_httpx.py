import httpx
try:
    r = httpx.get('http://matching-engine:8080/metrics', timeout=3)
    print('OK:', r.status_code)
    import re
    p50 = re.search(r'^exchange_latency_p50_ns\s+([\d.e+\-]+)', r.text, re.MULTILINE)
    print('P50:', p50.group(1) if p50 else 'NOT FOUND')
    # Print relevant lines
    for line in r.text.split('\n'):
        if 'exchange_latency' in line or 'exchange_orders' in line:
            print(line)
except Exception as e:
    print('ERROR:', e)
