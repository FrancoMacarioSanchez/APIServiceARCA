import base64
import uuid
import xml.etree.ElementTree as ET
from decimal import Decimal
import requests
from datetime import datetime, timedelta, timezone as dt_timezone

from django.conf import settings
from django.utils import timezone
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs7

from .models import ArcaToken

# =========================================================
# CONSTANTES
# =========================================================
WSAA_URLS = {
    "HOMOLOGACION": "https://wsaahomo.afip.gov.ar/ws/services/LoginCms",
    "PRODUCCION": "https://wsaa.afip.gov.ar/ws/services/LoginCms",
}
WSFE_URLS = {
    "HOMOLOGACION": "https://wswhomo.afip.gov.ar/wsfev1/service.asmx",
    "PRODUCCION": "https://servicios1.afip.gov.ar/wsfev1/service.asmx",
}

# =========================================================
# LECTURA DE CERTIFICADOS
# =========================================================
def _obtener_certificado():
    path = settings.ARCA_CERT_PATH
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        raise RuntimeError(f"No existe el certificado ARCA en la ruta indicada: {path}")

def _obtener_clave():
    path = settings.ARCA_KEY_PATH
    try:
        with open(path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        raise RuntimeError(f"No existe la clave privada ARCA en la ruta indicada: {path}")

# =========================================================
# WSAA: AUTENTICACIÓN
# =========================================================
def crear_login_ticket(servicio="wsfe"):
    ahora = datetime.now(dt_timezone.utc)
    generacion = ahora - timedelta(minutes=10)
    expiracion = ahora + timedelta(minutes=10)
    unique_id = int(uuid.uuid4().int % 2147483647)

    root = ET.Element("loginTicketRequest", {"version": "1.0"})
    header = ET.SubElement(root, "header")
    ET.SubElement(header, "uniqueId").text = str(unique_id)
    ET.SubElement(header, "generationTime").text = generacion.isoformat()
    ET.SubElement(header, "expirationTime").text = expiracion.isoformat()
    ET.SubElement(root, "service").text = servicio

    return ET.tostring(root, encoding="UTF-8", xml_declaration=True)

def firmar_login_ticket(xml):
    certificado = x509.load_pem_x509_certificate(_obtener_certificado())
    clave = serialization.load_pem_private_key(_obtener_clave(), password=None)

    builder = (
        pkcs7.PKCS7SignatureBuilder()
        .set_data(xml)
        .add_signer(certificado, clave, hashes.SHA256())
    )
    cms = builder.sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.Binary])
    return base64.b64encode(cms).decode("ascii")

def solicitar_token_wsaa(cms_base64, ambiente="HOMOLOGACION"):
    url = WSAA_URLS[ambiente]
    soap_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:wsaa="http://wsaa.view.sua.dvadac.desein.afip.gov">
    <soapenv:Header/>
    <soapenv:Body><wsaa:loginCms><wsaa:in0>{cms_base64}</wsaa:in0></wsaa:loginCms></soapenv:Body>
</soapenv:Envelope>"""

    headers = {"Content-Type": "text/xml; charset=UTF-8", "SOAPAction": '"loginCms"'}
    
    response = requests.post(url, data=soap_body.encode("utf-8"), headers=headers, timeout=30)
    if response.status_code != 200:
        raise RuntimeError(f"WSAA error HTTP {response.status_code}: {response.text[:500]}")
    return response.text

def parsear_token_wsaa(xml_text):
    root = ET.fromstring(xml_text)
    
    # Función auxiliar para ignorar los namespaces de SOAP (ej: {http://...}loginCmsReturn)
    def local_name(tag):
        return tag.split("}", 1)[1] if "}" in tag else tag

    login_cms_return = None
    for elem in root.iter():
        if local_name(elem.tag) == "loginCmsReturn":
            login_cms_return = elem
            break

    if login_cms_return is None or not login_cms_return.text:
        raise RuntimeError(f"WSAA no devolvió loginCmsReturn. Respuesta: {xml_text[:500]}")

    ticket_root = ET.fromstring(login_cms_return.text)
    
    token = sign = exp_text = None
    for elem in ticket_root.iter():
        nombre = local_name(elem.tag)
        if nombre == "token":
            token = elem.text
        elif nombre == "sign":
            sign = elem.text
        elif nombre == "expirationTime":
            exp_text = elem.text

    expiracion = datetime.fromisoformat(exp_text.replace("Z", "+00:00"))
    return token, sign, expiracion

def obtener_token_wsfe():
    ambiente = settings.ARCA_AMBIENTE
    token_db = ArcaToken.objects.filter(servicio="wsfe", ambiente=ambiente).order_by("-expiracion").first()
    
    if token_db and token_db.esta_vigente():
        return token_db

    xml_ticket = crear_login_ticket()
    cms_base64 = firmar_login_ticket(xml_ticket)
    respuesta_wsaa = solicitar_token_wsaa(cms_base64, ambiente)
    token, sign, expiracion = parsear_token_wsaa(respuesta_wsaa)

    return ArcaToken.objects.create(
        servicio="wsfe",
        ambiente=ambiente,
        token=token,
        sign=sign,
        expiracion=expiracion
    )

# =========================================================
# WSFE: FACTURACIÓN
# =========================================================
def solicitar_wsfe(soap_body, soap_action):
    ambiente = settings.ARCA_AMBIENTE
    url = WSFE_URLS[ambiente]
    headers = {
        "Content-Type": "text/xml; charset=UTF-8",
        "SOAPAction": f'"{soap_action}"',
    }
    response = requests.post(url, data=soap_body.encode("utf-8"), headers=headers, timeout=30)
    if response.status_code != 200:
        raise RuntimeError(f"WSFEv1 error HTTP {response.status_code}: {response.text[:500]}")
    return response.text

def obtener_ultimo_comprobante(token, cuit_emisor, punto_venta, tipo_comprobante):
    soap_body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ar="http://ar.gov.afip.dif.FEV1/">
   <soapenv:Body>
      <ar:FECompUltimoAutorizado>
         <ar:Auth>
            <ar:Token>{token.token}</ar:Token>
            <ar:Sign>{token.sign}</ar:Sign>
            <ar:Cuit>{cuit_emisor}</ar:Cuit>
         </ar:Auth>
         <ar:PtoVta>{punto_venta}</ar:PtoVta>
         <ar:CbteTipo>{tipo_comprobante}</ar:CbteTipo>
      </ar:FECompUltimoAutorizado>
   </soapenv:Body>
</soapenv:Envelope>"""

    respuesta = solicitar_wsfe(soap_body, "http://ar.gov.afip.dif.FEV1/FECompUltimoAutorizado")
    root = ET.fromstring(respuesta)
    cbte_nro = root.find(".//{http://ar.gov.afip.dif.FEV1/}CbteNro")
    
    if cbte_nro is None:
        raise RuntimeError(f"WSFEv1 no devolvió CbteNro: {respuesta[:500]}")
    return int(cbte_nro.text)

def emitir_factura_arca(payload, cuit_emisor, punto_venta):
    """
    Recibe los datos crudos del sistema origen y se comunica con WSFE.
    Retorna un diccionario estructurado con la respuesta.
    """
    token = obtener_token_wsfe()
    tipo_arca = payload.get("tipo_comprobante", 11) # Por defecto FC (11)
    
    # 1. Obtener número de comprobante
    ultimo_nro = obtener_ultimo_comprobante(token, cuit_emisor, punto_venta, tipo_arca)
    numero_nuevo = ultimo_nro + 1

    # 2. Armar XML de FECAESolicitar
    def tag(parent, name, value):
        el = ET.SubElement(parent, f"ar:{name}")
        el.text = str(value)
        return el

    envelope = ET.Element("soapenv:Envelope", {
        "xmlns:soapenv": "http://schemas.xmlsoap.org/soap/envelope/",
        "xmlns:ar": "http://ar.gov.afip.dif.FEV1/"
    })
    body = ET.SubElement(envelope, "soapenv:Body")
    solicitud = ET.SubElement(body, "ar:FECAESolicitar")
    
    auth = ET.SubElement(solicitud, "ar:Auth")
    tag(auth, "Token", token.token)
    tag(auth, "Sign", token.sign)
    tag(auth, "Cuit", cuit_emisor)

    req = ET.SubElement(solicitud, "ar:FeCAEReq")
    cabecera = ET.SubElement(req, "ar:FeCabReq")
    tag(cabecera, "CantReg", 1)
    tag(cabecera, "PtoVta", punto_venta)
    tag(cabecera, "CbteTipo", tipo_arca)

    detalles = ET.SubElement(req, "ar:FeDetReq")
    detalle = ET.SubElement(detalles, "ar:FECAEDetRequest")
    
    # Mapeo de datos del payload
    total = f"{float(payload.get('monto_total', 0)):.2f}"
    fecha_cbte = datetime.now().strftime("%Y%m%d")
    
    tag(detalle, "Concepto", payload.get("concepto", 1)) # 1: Productos, 2: Servicios
    tag(detalle, "DocTipo", payload.get("cliente_doc_tipo", 99)) # 99: Consumidor Final
    tag(detalle, "DocNro", payload.get("cliente_doc_nro", 0))
    tag(detalle, "CbteDesde", numero_nuevo)
    tag(detalle, "CbteHasta", numero_nuevo)
    tag(detalle, "CbteFch", fecha_cbte)
    tag(detalle, "ImpTotal", total)
    tag(detalle, "ImpTotConc", "0.00")
    tag(detalle, "ImpNeto", total) # Asumiendo Factura C o Exento
    tag(detalle, "ImpOpEx", "0.00")
    tag(detalle, "ImpIVA", "0.00")
    tag(detalle, "ImpTrib", "0.00")
    tag(detalle, "MonId", "PES")
    tag(detalle, "MonCotiz", "1.000000")
    
    # Nuevo tag obligatorio según RG 5616 (Ej: 5 es Consumidor Final)
    tag(detalle, "CondicionIVAReceptorId", payload.get("cliente_condicion_iva", 5))

    soap_body_str = ET.tostring(envelope, encoding="utf-8", xml_declaration=True).decode("utf-8")

    # 3. Enviar petición
    respuesta_xml = solicitar_wsfe(soap_body_str, "http://ar.gov.afip.dif.FEV1/FECAESolicitar")
    root = ET.fromstring(respuesta_xml)

    # 4. Parsear respuesta
    def extract(name):
        nodo = root.find(f".//{{http://ar.gov.afip.dif.FEV1/}}{name}")
        return nodo.text if nodo is not None else ""

    resultado = extract("Resultado")
    cae = extract("CAE")
    cae_vencimiento = extract("CAEFchVto")
    
    # Capturar Errores y Observaciones de AFIP de manera segura
    errores = []
    for err in root.findall(".//{http://ar.gov.afip.dif.FEV1/}Err"):
        code_node = err.find("{http://ar.gov.afip.dif.FEV1/}Code")
        msg_node = err.find("{http://ar.gov.afip.dif.FEV1/}Msg")
        if code_node is not None and msg_node is not None:
            errores.append(f"Error {code_node.text}: {msg_node.text}")

    for obs in root.findall(".//{http://ar.gov.afip.dif.FEV1/}Obs"):
        code_node = obs.find("{http://ar.gov.afip.dif.FEV1/}Code")
        msg_node = obs.find("{http://ar.gov.afip.dif.FEV1/}Msg")
        if code_node is not None and msg_node is not None:
            errores.append(f"Obs {code_node.text}: {msg_node.text}")

    return {
        "resultado": resultado,
        "cae": cae,
        "cae_vencimiento": cae_vencimiento,
        "numero_asignado": numero_nuevo if resultado == "A" else None,
        "errores": errores,
        "xml_crudo": respuesta_xml
    }