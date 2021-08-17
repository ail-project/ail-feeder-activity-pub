import requests


# https://instances.social/api/doc/
token = '<token>'
response = requests.get("https://instances.social/api/1.0/instances/list?count=0&include_down=false&include_closed=false", headers={'Authorization': f'Bearer {token}'})
result = response.json()
with open('instances.txt', 'w') as f:
    for i in result['instances']:
        f.write(f"{i['name']}\n")
