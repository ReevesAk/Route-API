from django.http import HttpResponse


def scalar_ui(request):
    html = """<!doctype html>
<html>
  <head>
    <title>Fuel Route API</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
  </head>
  <body>
    <script
      id="api-reference"
      data-url="/api/schema/"
      data-configuration='{"theme":"purple"}'
    ></script>
    <script src="https://cdn.jsdelivr.net/npm/@scalar/api-reference"></script>
  </body>
</html>"""
    return HttpResponse(html)
