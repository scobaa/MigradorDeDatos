import xmlrpc.client

url = "https://tes-importaciones.cloudpepper.site"
db = "tes-importaciones.cloudpepper.site"
username = "admin"
password = "1234"

common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
uid = common.authenticate(db, username, password, {})
models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

print("Checking if test invoice exists...")
recs = models.execute_kw(
    db, uid, password,
    "account.move", "search_read",
    [[("name", "=", "TEST-INV-9999")]], {"fields": ["id", "state"]}
)
print("Found:", recs)

if recs:
    move_id = recs[0]["id"]
    state = recs[0]["state"]
    if state == "posted":
        print("Changing to draft...")
        try:
            models.execute_kw(db, uid, password, "account.move", "button_draft", [[move_id]])
        except Exception as e:
            print("button_draft raised exception (possibly serialization error, ignoring):", e)
            
    print("Deleting invoice...")
    try:
        models.execute_kw(db, uid, password, "account.move", "unlink", [[move_id]])
        print("Invoice deleted successfully!")
    except Exception as e:
        print("Error deleting invoice:", e)
else:
    print("Invoice TEST-INV-9999 already deleted or does not exist.")
