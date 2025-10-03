from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from cryptography.hazmat.primitives.asymmetric import rsa
from config import KeyConfig
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
# 加载公钥和私钥，返回公钥和私钥对象
def load_keys(private_key_path:str,pub_key_path:str,pub_key_control_path)->tuple[RSAPrivateKey,RSAPublicKey,RSAPublicKey]:
    with open(private_key_path, "rb") as f:
        private_key_A = serialization.load_pem_private_key(
            f.read(),
            password=None,   # 如果加密过，就填密码
        )

    # 加载公钥
    with open(pub_key_path, "rb") as f:
        public_key_A = serialization.load_pem_public_key(f.read())
    with open(pub_key_control_path,"rb") as f:
        public_control=serialization.load_pem_public_key(f.read())

    return (private_key_A,public_key_A,public_control)

def generate_keys()->tuple[RSAPrivateKey,RSAPublicKey]:
    private_key_A = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key_A = private_key_A.public_key()
    return (private_key_A,public_key_A)

def write_keys(path:str,key):
    # 保存私钥到文件
    if type(key)==RSAPrivateKey:
        with open(path, "wb") as f:
            f.write(
                key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,   # 通用私钥格式
                    encryption_algorithm=serialization.NoEncryption()
                )
            )
    elif type(key)==RSAPublicKey:
        with open(path, "wb") as f:
            f.write(
                key.public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo  # 标准公钥格式
                )
            )

#加密信息
def encryption(message:str,public_key_B:RSAPublicKey)->bytes:
    ciphertext = public_key_B.encrypt(
        message,
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None)
    )
    return ciphertext

#签名信息
def signature(message:str)->bytes:
    PRIVATE_KEY_A,PUBLIC_KEY_A,_=load_keys(KeyConfig.PRIVATE_KEY_PATH,KeyConfig.PUBLIC_KEY_PATH,KeyConfig.PUBLIC_KEY_CONTROL)
    signature = PRIVATE_KEY_A.sign(
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256()
    )
    return signature

#解密信息
def decryption(ciphertext:bytes)->bytes:
    PRIVATE_KEY_A,PUBLIC_KEY_A,_=load_keys(KeyConfig.PRIVATE_KEY_PATH,KeyConfig.PUBLIC_KEY_PATH,KeyConfig.PUBLIC_KEY_CONTROL)
    plaintext = PRIVATE_KEY_A.decrypt(
        ciphertext,
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None)
    )
    return plaintext

#验证签名
def verify_signature(message:bytes, signature:bytes)->bool:
    _,_,public_key_B=load_keys(KeyConfig.PRIVATE_KEY_PATH,KeyConfig.PUBLIC_KEY_PATH,KeyConfig.PUBLIC_KEY_CONTROL)
    try:
        public_key_B.verify(
            signature,
            message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                       salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256()
        )
        return True
    except Exception:
        return False