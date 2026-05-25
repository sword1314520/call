import oss2
from dotenv import load_dotenv
import os

# 加载配置
load_dotenv()

# 严格按照你源代码的写法读取
access_key_id = os.getenv("OSS_ACCESS_KEY_ID")
access_key_secret = os.getenv("OSS_ACCESS_KEY_SECRET")
endpoint = os.getenv("OSS_ENDPOINT")
bucket_name = os.getenv("OSS_BUCKET_NAME")  # 这里必须和你源码一样！

# 打印看看是否正确读取
print("==== 你的 OSS 配置 ====")
print("ENDPOINT :", endpoint)
print("BUCKET_NAME :", bucket_name)
print("ACCESS_KEY_ID :", access_key_id)
print("ACCESS_KEY_SECRET :", access_key_secret)

try:
    auth = oss2.Auth(access_key_id, access_key_secret)
    bucket = oss2.Bucket(auth, endpoint, bucket_name)

    # 测试连接
    result = bucket.list_objects_v2(max_keys=3)
    print("\n✅ OSS 连接成功！配置完全正确！")

except Exception as e:
    print("\n❌ OSS 连接失败：", str(e))