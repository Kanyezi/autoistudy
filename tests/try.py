import requests

url = "https://www.zjcai.com/account/logon"

#UserName=0253240139&Password=123456
data = {
    "UserName": "0253240139",
    "Password": "123456",
}

response = requests.post(url, data=data)
print(response.text)
