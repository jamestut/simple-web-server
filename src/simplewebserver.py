import uvicorn
import argparse
import os
import collections
import multipart_stream

args = None

EMPTY_RESPONSE = {
    'type': 'http.response.body',
    'body': b''
}

def gen_header(status=200, content_type=None, custom_headers=[]):
    obj = {
        'type': 'http.response.start',
        'status': status,
        'headers': []
    }
    if content_type is not None:
        obj['headers'].extend([
            [b'content-type', content_type.encode('UTF-8')],
            [b'Access-Control-Allow-Origin', b'*']
        ])
    obj['headers'].extend(custom_headers)
    return obj


def gen_abs_path(scope, path):
    # default host value if not set in header
    host = scope["server"][0] + (':' + str(scope["server"][1]) if scope["server"][1] != 80 else "")
    # look for host header
    for header in scope["headers"]:
        if header[0].decode() == "host":
            host = header[1].decode()
            break

    return f'{scope["scheme"]}://{host}{path}'

def gen_text_response(message):
    return {
        'type': 'http.response.body',
        'body': message.encode('UTF-8')
    }


def human_size(size):
    fmtstr = "{0:.2f} {1}"
    if size > 1000000000:
        unit = "GB"
        szf = size / 1000000000
    elif size > 1000000:
        unit = "MB"
        szf = size / 1000000
    elif size > 1000:
        unit = "kB"
        szf = size / 1000
    else:
        unit = "B"
        szf = size
        fmtstr = "{0:.0f} {1}"

    return fmtstr.format(szf, unit)


def create_dir_list_page(scdiriter, pwd):
    template_begin = """
    <!doctype html>
    <html>
    <head><title>Directory Listing</title></head>
    <body>
        <table>
            <tr>
                <th align="left">Name</th>
                <th align="left">Size</th>
            </tr>
    """
    template_end = """
        </table>
        <hr>
        <form method="POST" enctype="multipart/form-data">
            <input type="file" name="data" />
            <input type="submit"/>
        </form>
        </body>
    </html>
    """

    dirs = collections.OrderedDict()
    files = collections.OrderedDict()

    for f in scdiriter:
        if f.is_dir():
            dirs[f.name] = (f.path[1:],)
        else:
            try:
                size = f.stat().st_size
            except:
                size = -1
            files[f.name] = (f.path[1:], size,)
        pass
    scdiriter.close()

    # we use list for quicker concat. this is akin to stringbuilder.
    retarr = [template_begin]
    # go up!
    if pwd != '/':
        parentpath = os.path.normpath(os.path.join(pwd, '..'))
        retarr.append(f'<tr><td><a href="{parentpath}">Up One Level</a></td><td></td></tr>')
    # directories first, then files
    for dir, md in dirs.items():
        retarr.append(f'<tr><td><a href="{md[0]}">{dir}</a></td><td>(dir)</td></tr>')
    for file, md in files.items():
        retarr.append(f'<tr><td><a href="{md[0]}">{file}</a></td><td>{human_size(md[1])}</td></tr>')
    retarr.append(template_end)

    return "".join(retarr)


async def download_file(path, send):
    buffsz = 262144
    buff = b''
    try:
        with open(path, 'rb') as fh:
            filesize = os.fstat(fh.fileno()).st_size
            aux_header = []
            if filesize > 0:
                aux_header.append([b'content-length', str(filesize).encode('UTF-8')])
            await send(gen_header(200, "application/octet-stream", aux_header))
            while True:
                buff = fh.read(buffsz)
                if len(buff) <= 0:
                    await send(EMPTY_RESPONSE)
                    break
                await send({
                    'type': 'http.response.body',
                    'body': buff,
                    'more_body': True
                })
    except PermissionError as ex:
        await send(gen_header(403))
        await send(gen_text_response(str(ex)))
    except Exception as ex:
        await send(gen_header(500))
        await send(gen_text_response(str(ex)))


async def upload_file(canopath, path, scope, send, receive):
    try:
        with multipart_stream.MultipartStream(scope, path, b'data') as msreader:
            more_body = True
            while more_body:
                msg = await receive()
                # debug
                body = msg.get('body', b'')
                print(f"Received chunk size: {len(body)} bytes.")
                msreader.add_chunk(body)
                more_body = msg.get('more_body', False)
            # tell the client to refresh the page using GET!
            redir_hdr = [[b'location', gen_abs_path(scope, canopath).encode('UTF-8')]]
            await send(gen_header(303, custom_headers=redir_hdr))
            await send(EMPTY_RESPONSE)
    except PermissionError as ex:
        await send(gen_header(403))
        await send(gen_text_response(str("Writing to this resource is not allowed.")))
    except FileNotFoundError as ex:
        await send(gen_header(404))
        await send(gen_text_response("Parent directory not found."))
    except Exception as ex:
        await send(gen_header(500))
        await send(gen_text_response(str(ex)))


async def app(scope, receive, send):
    assert scope['type'] == 'http'
    canopath = os.path.normpath(scope['path'])
    if scope['path'] != canopath:
        await send(gen_header(301, custom_headers=[[b'location', gen_abs_path(scope, canopath).encode('UTF-8')]]))
        await send(EMPTY_RESPONSE)
        return

    path = '.' + canopath

    if scope['method'] in ('HEAD', 'GET'):
        if os.path.isdir(path):
            try:
                scan_iter = os.scandir(path)
                dirlist = gen_text_response(create_dir_list_page(scan_iter, canopath))
                await send(gen_header(200, "text/html"))
                await send(dirlist)
            except PermissionError as ex:
                await send(gen_header(403))
                await send(gen_text_response("Access to this resource is not allowed."))
                return
            except Exception as ex:
                await send(gen_header(500))
                await send(gen_text_response(str(ex)))
                return
        elif os.path.isfile(path):
            await download_file(path, send)
        else:
            await send(gen_header(404))
            await send(gen_text_response("Requested resource not found."))
    elif scope['method'] == 'POST':
        if os.path.isdir(path):
            await upload_file(canopath, path, scope, send, receive)
        else:
            await send(gen_header(405))
            await send(gen_text_response("Must POST inside a directory"))
    else:
        await send(gen_header(405))
        await send(EMPTY_RESPONSE)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="A simple static web server.")
    parser.add_argument("--port", type=int, default=8080, help="Port number to listen to.")
    parser.add_argument("--cwd", type=str, default='.', help="Base directory.")
    parser.add_argument("--bind", type=str, default='0.0.0.0', help="IP address to bind to.")
    args = parser.parse_args()
    os.chdir(args.cwd)
    uvicorn.run(app, host=args.bind, port=args.port, log_level="info")