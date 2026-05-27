import xmlrpc.client

url = "https://tes-importaciones.cloudpepper.site"
db = "tes-importaciones.cloudpepper.site"
username = "admin"
password = "1234"

print("Connecting...")
common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
uid = common.authenticate(db, username, password, {})
models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

print("Executing fields_get for type...")
res = models.execute_kw(
    db, uid, password,
    "product.template", "fields_get",
    [], {"allfields": ["type"], "attributes": ["selection"]}
)
print("Result:", res)
