#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import queue
import subprocess
import threading

from flask import Flask, app, redirect, url_for, render_template, request
from flask import send_file, abort, flash, session

from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'XXXXXXX'

task_queue = queue.Queue()
task_list = set()

def worker():
    while True:
        task = task_queue.get()
        try:
            print(f'starting {task}')
            task()
            print(f'end of {task}')
        except Exception as e:
            print(f'Error executing {task}: {e}')

threading.Thread(target=worker, daemon=True).start()

class Encode:
    """
    This is a task that is run asyncronously to convert the movie using ffmpeg
    """
    def __init__(self, mov, sub, outf):
        self.mov = mov
        self.sub = sub
        self.outf = outf
        self.name = self.mov.split('/')[-1][:60]
        self.state = 'idle'

    def __str__(self):
        return f'{self.name}: [{self.state}] {self.progress()}%'

    def __call__(self):
        self.state = 'running'
        print(f'Star processing {self.name}')
        cmd = [ 'ffmpeg',
            '-fflags', '+genpts', '-y',
            '-i', self.mov, '-i', self.sub,
            #'-map', '0', '-map', '1', '-c', 'copy', 
            '-map', '0', '-map', '-0:s', '-map', '1', '-c', 'copy', # remove all sub from the source
            self.outf ] 
        cp = subprocess.run(cmd, stderr=subprocess.PIPE, check=False)
        if cp.returncode == 0:
            self.state = 'OK'
        else:
            self.state = f'Err: {cp.stderr}'

    def progress(self):
        try:
            infile_sz = os.stat(self.mov).st_size
            ofile_sz = os.stat(self.outf).st_size
            return int(100 * ofile_sz / infile_sz)
        except FileNotFoundError:
            return 0



BASE_DIR = '/mnt/media/downloads/videos'
UPLOAD_FOLDER = '/mnt/media/downloads/subs'
ALLOWED_EXTENSIONS = set(['srt', 'sub'])


@app.template_filter('to_human')
def to_human(x):
    if isinstance(x, str):
        x = float(x)
    prefix = ' kMGTP'
    for a in prefix:
        if x < 1024.0:
            return '{x:.1f}{a}'.format(x=x, a=a)
        x /= 1024.0
    return '{x:.1f}{a}'.format(x=x, a=a)



@app.template_filter('get_dir')
def get_dir(f):
    p = os.path.relpath(f, BASE_DIR)
    #print("f=[%s] p={%s}" % (f, p))
    return os.fsdecode(p)


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    #return redirect(url_for('dir_listing'))
    return render_template('index.html')

@app.route('/dir/', defaults={'req_path': ''})
@app.route('/dir/<path:req_path>')
def dir_listing(req_path):

    # Joining the base and the requested path
    abs_path = os.path.join(BASE_DIR, req_path)

    # Return 404 if path doesn't exist
    if not os.path.exists(abs_path):
        return abort(404)

    # Check if path is a file and serve
    if os.path.isfile(abs_path):
        return send_file(abs_path)

    # Show directory contents
    files = list(os.scandir(abs_path))
    dirs = [ x for x in files if x.is_dir()]
    dirs.sort(key=lambda x: x.name)
    videos = [ x for x in files if x.name.endswith((
        '.mkv', '.mp4', '.avi', '.srt'
        )) ]
    videos.sort(key=lambda x: x.name)
    tl = get_task_list()
    print(tl)
    return render_template('dir_list.html', dirs=dirs,
            videos=videos, tl=tl)

@app.route('/info/<path:f>')
def info(f):
    # Joining the base and the requested path
    abs_path = os.path.join(BASE_DIR, f)

    # Return 404 if path doesn't exist
    if not os.path.exists(abs_path):
        return abort(404)

    # Check if path is a file and serve
    if not os.path.isfile(abs_path):
        return abort(505)

    res = subprocess.run([
        'ffmpeg', '-i', abs_path
        ], stderr=subprocess.PIPE).stderr
    res = res.decode()
    res = res.splitlines()
    streams = [x.strip() for x in res if 'Stream #0:' in x 
            or 'Duration:' in x]
    basename = os.path.basename(abs_path)
    return render_template('file_info.html', streams=streams,
		filename=f, basename=basename)


@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        # check if the post request has the file part
        if 'file' not in request.files:
            flash('No file part')
            return redirect(request.url)
        file = request.files['file']
        mov = request.form['mov']
        # if user does not select file, browser also
        # submit an empty part without filename
        if file.filename == '':
            flash('No selected file')
            return redirect(request.url)
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            sub_path = os.path.join(UPLOAD_FOLDER, filename)
            # out_name = filename.rsplit('.',1)[0] + '.mkv'
            out_name = os.path.basename(mov)
            out_path = os.path.join(UPLOAD_FOLDER, out_name)
            mov_path = os.path.join(BASE_DIR, mov)
            bcontent = file.stream.read()
            print("Saving subtitles: " + filename)
            try:
                content = bcontent.decode('utf-8')
                print("Decoded as UTF-8")
            except UnicodeDecodeError:
                content = bcontent.decode('cp1251')
                print("Decoded as CP-1251")
            with open(sub_path, 'w', encoding="utf-8") as outf:
                outf.write(content)

            run_ffmpeg(mov_path, sub_path, out_path)

            return redirect(url_for('dir_listing'))
    return render_template('file_info.html', **request.form)

def run_ffmpeg(mov, sub, outf):
    task = Encode(mov, sub, outf)
    task_list.add(task)
    task_queue.put(task)
    flash(f"Task is added: {str(task)}")


def get_task_list():
    return [str(t) for t in task_list]

@app.route('/tl')
def gtl():
    return "\n".join(get_task_list())


def main():

    app.run(host='::', port=80, debug=True)

if __name__ == '__main__':
    main()
