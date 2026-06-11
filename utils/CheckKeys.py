from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey
from cryptography.hazmat.primitives.asymmetric import rsa
from ..config import KeyConfig
# cryptography imports for hybrid encryption
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import json
import base64
import os
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

#加密信息 这里因为可能会有较大数据，所以采用混合加密，消息体用AES-GCM对称加密，AES密钥用RSA非对称加密
def encryption(message:str)->bytes:
    # Hybrid encryption: AES-GCM + RSA-OAEP for AES key
    _,_,PUBLIC_KEY_B = load_keys(KeyConfig.PRIVATE_KEY_PATH, KeyConfig.PUBLIC_KEY_PATH, KeyConfig.PUBLIC_KEY_PATH)
    if isinstance(message, str):
        message = message.encode('utf-8')
    aes_key = AESGCM.generate_key(bit_length=128)
    aesgcm = AESGCM(aes_key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, message, None)
    enc_key = PUBLIC_KEY_B.encrypt(
        aes_key,
        padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                     algorithm=hashes.SHA256(),
                     label=None)
    )
    payload = {
        "enc_key": base64.b64encode(enc_key).decode('utf-8'),
        "nonce": base64.b64encode(nonce).decode('utf-8'),
        "ciphertext": base64.b64encode(ciphertext).decode('utf-8')
    }
    return json.dumps(payload).encode('utf-8')

#签名信息
def signature(message:str)->bytes:
    PRIVATE_KEY_A,_,_=load_keys(KeyConfig.PRIVATE_KEY_PATH,KeyConfig.PUBLIC_KEY_PATH,KeyConfig.PUBLIC_KEY_PATH)
    signature = PRIVATE_KEY_A.sign(
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256()
    )
    return signature

#解密信息
def decryption(ciphertext:bytes)->bytes:
    PRIVATE_KEY_A,_,_=load_keys(KeyConfig.PRIVATE_KEY_PATH,KeyConfig.PUBLIC_KEY_PATH,KeyConfig.PUBLIC_KEY_PATH)
    # Attempt hybrid decryption first
    try:
        raw = ciphertext.decode('utf-8')
        payload = json.loads(raw)
        enc_key = base64.b64decode(payload.get('enc_key'))
        nonce = base64.b64decode(payload.get('nonce'))
        ct = base64.b64decode(payload.get('ciphertext'))
        aes_key = PRIVATE_KEY_A.decrypt(
            enc_key,
            padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                         algorithm=hashes.SHA256(),
                         label=None)
        )
        aesgcm = AESGCM(aes_key)
        plaintext = aesgcm.decrypt(nonce, ct, None)
        return plaintext
    except Exception:
        # fallback to legacy RSA decrypt
        try:
            plaintext = PRIVATE_KEY_A.decrypt(
                ciphertext,
                padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                            algorithm=hashes.SHA256(),
                            label=None)
            )
            return plaintext
        except Exception as e:
            print("[Decryption error fallback failed]", e)
            return b""

#验证签名
def verify_signature(message:bytes, signature:bytes)->bool:
    _,_,public_key_B=load_keys(KeyConfig.PRIVATE_KEY_PATH,KeyConfig.PUBLIC_KEY_PATH,KeyConfig.PUBLIC_KEY_PATH)
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
    
def get_verified_msg(recived_message:dict)->dict:
    import datetime as _dt
    _t0 = _dt.datetime.now()
    try:
        encrypted_msg = recived_message.get("message")
        signature_data = recived_message.get("signature")

        if isinstance(encrypted_msg, str):
            encrypted_msg = base64.b64decode(encrypted_msg)
        if isinstance(signature_data, str):
            signature_data = base64.b64decode(signature_data)

        if not encrypted_msg or not signature_data:
            return {}

        if isinstance(encrypted_msg, str):
            encrypted_msg = encrypted_msg.encode()
        if isinstance(signature_data, str):
            signature_data = signature_data.encode()
        _t1 = _dt.datetime.now()

        try:
            decrypted_msg = decryption(encrypted_msg)
        except Exception as e:
            _te = _dt.datetime.now()
            print(f"[perf][node] verify_msg FAILED decrypt after {(_te-_t0).total_seconds()*1000:.0f}ms: {e}")
            return {}
        _t2 = _dt.datetime.now()

        if not verify_signature(decrypted_msg, signature_data):
            _te = _dt.datetime.now()
            print(f"[perf][node] verify_msg FAILED signature after {(_te-_t0).total_seconds()*1000:.0f}ms")
            return {}
        _t3 = _dt.datetime.now()

        try:
            message_dict = json.loads(decrypted_msg.decode('utf-8'))
        except Exception as e:
            _te = _dt.datetime.now()
            print(f"[perf][node] verify_msg FAILED json after {(_te-_t0).total_seconds()*1000:.0f}ms: {e}")
            return {}

        _t4 = _dt.datetime.now()
        _b64 = (_t1-_t0).total_seconds()*1000
        _dec = (_t2-_t1).total_seconds()*1000
        _vrf = (_t3-_t2).total_seconds()*1000
        _jsn = (_t4-_t3).total_seconds()*1000
        print(f"[perf][node] verify_msg  b64={_b64:.0f}ms  decrypt={_dec:.0f}ms  verify={_vrf:.0f}ms  json={_jsn:.0f}ms")
        return message_dict
    except Exception as e:
        _te = _dt.datetime.now()
        print(f"[perf][node] verify_msg FAILED after {(_te-_t0).total_seconds()*1000:.0f}ms: {e}")
        return {}