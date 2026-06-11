import glob
for f in glob.glob('python-engine/migrator/*.py'):
    with open(f, 'r', encoding='utf-8') as file:
        content = file.read()
    content = content.replace('"current":', '"done":')
    content = content.replace("'current':", "'done':")
    with open(f, 'w', encoding='utf-8') as file:
        file.write(content)
print("Replaced current with done in all migrator files")
