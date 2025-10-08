import runpy,traceback,sys

try:
    print('Running src/app.py...')
    runpy.run_path('src/app.py', run_name='__main__')
except Exception:
    traceback.print_exc()
    sys.exit(1)
else:
    print('Completed without exception')
