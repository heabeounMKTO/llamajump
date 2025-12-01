import requests
from flask import Flask, request, Response, jsonify, stream_with_context
import logging
from datetime import datetime
import os


app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

LLAMA_SERVER = os.getenv("LLAMA_SERVER", "http://localhost:9997")
PORT = int(os.getenv("PORT", "8080"))


@app.route('/health')
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'running',
        'target': LLAMA_SERVER,
        'timestamp': datetime.now().isoformat()
    })

def is_streaming_request():
    """Check if this is likely a streaming request"""
    # Check for streaming indicators
    accept_header = request.headers.get('Accept', '')
    stream_param = request.args.get('stream', '').lower()

    # Check if request body indicates streaming
    is_stream_request = False
    if request.is_json:
        try:
            data = request.get_json()
            if isinstance(data, dict):
                is_stream_request = data.get('stream', False)
        except:
            pass

    return (
        'text/event-stream' in accept_header or
        'application/x-ndjson' in accept_header or
        stream_param in ['true', '1', 'yes'] or
        is_stream_request
    )

def proxy_streaming_response(target_url, headers, data):
    def generate():
        try:
            with requests.request(
                method=request.method,
                url=target_url,
                headers=headers,
                data=data,
                params=request.args,
                stream=True,  
                timeout=(10, None)  # 10s connection timeout and no read timeout
            ) as resp:

                logger.info(f"[{datetime.now().isoformat()}] Streaming response: {resp.status_code} for {request.method} {request.url}")
                if resp.status_code != 200:
                    yield f"HTTP/1.1 {resp.status_code} {resp.reason}\n"

                for chunk in resp.iter_content(chunk_size=1024, decode_unicode=False):
                    if chunk:
                        yield chunk

        except requests.exceptions.ConnectionError:
            logger.error(f"Streaming connection error: Unable to connect to {LLAMA_SERVER}")
            error_response = {
                'error': 'Connection error',
                'message': f'Unable to connect to llama.cpp server at {LLAMA_SERVER}'
            }
            yield f"data: {error_response}\n\n"

        except Exception as e:
            logger.error(f"Streaming proxy error: {str(e)}")
            error_response = {
                'error': 'Streaming error',
                'message': str(e)
            }
            yield f"data: {error_response}\n\n"

    try:
        resp = requests.request(
            method=request.method,
            url=target_url,
            headers=headers,
            data=data,
            params=request.args,
            stream=True,
            timeout=(10, None)
        )

        excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
        response_headers = [
            (key, value) for key, value in resp.headers.items()
            if key.lower() not in excluded_headers
        ]

        response_headers.append(('Cache-Control', 'no-cache'))
        response_headers.append(('Connection', 'keep-alive'))

        def stream_generator():
            for chunk in resp.iter_content(chunk_size=1024, decode_unicode=False):
                if chunk:
                    yield chunk

        return Response(
            stream_with_context(stream_generator()),
            status=resp.status_code,
            headers=response_headers,
            mimetype=resp.headers.get('content-type', 'text/plain')
        )

    except Exception as e:
        logger.error(f"Error setting up streaming: {str(e)}")
        return jsonify({
            'error': 'Streaming setup error',
            'message': str(e)
        }), 500

@app.route('/', defaults={'path': ''}, methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
@app.route('/<path:path>', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
def proxy(path):
    """Forward all requests to llama.cpp server with streaming support"""

    target_url = f"{LLAMA_SERVER}/{path}"
    if request.query_string:
        target_url += f"?{request.query_string.decode()}"
    logger.info(f"[{datetime.now().isoformat()}] Proxying: {request.method} {request.url} -> {target_url}")

    headers = {}
    for key, value in request.headers:
        if key.lower() not in ['host', 'connection', 'transfer-encoding']:
            headers[key] = value

    data = request.get_data()

    if is_streaming_request():
        logger.info(f"[{datetime.now().isoformat()}] Detected streaming request")
        return proxy_streaming_response(target_url, headers, data)

    try:
        resp = requests.request(
            method=request.method,
            url=target_url,
            headers=headers,
            data=data,
            params=request.args,
            allow_redirects=False,
            timeout=300  # 5 minutes timeout for non-streaming
        )

        logger.info(f"[{datetime.now().isoformat()}] Response: {resp.status_code} for {request.method} {request.url}")

        excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
        response_headers = [
            (key, value) for key, value in resp.headers.items()
            if key.lower() not in excluded_headers
        ]

        return Response(
            response=resp.content,
            status=resp.status_code,
            headers=response_headers
        )

    except requests.exceptions.ConnectionError:
        logger.error(f"Connection error: Unable to connect to {LLAMA_SERVER}")
        return jsonify({
            'error': 'Connection error',
            'message': f'Unable to connect to llama.cpp server at {LLAMA_SERVER}'
        }), 502

    except requests.exceptions.Timeout:
        logger.error(f"Timeout error: Request to {LLAMA_SERVER} timed out")
        return jsonify({
            'error': 'Timeout error',
            'message': 'Request to llama.cpp server timed out'
        }), 504

    except Exception as e:
        logger.error(f"Proxy error: {str(e)}")
        return jsonify({
            'error': 'Proxy error',
            'message': str(e)
        }), 500

if __name__ == '__main__':
    print(f"Starting streaming proxy server...")
    print(f"Forwarding requests to: {LLAMA_SERVER}")
    print(f"Proxy will be available at: http://localhost:8080")
    print(f"Health check: http://localhost:8080/health")
    print(f"Streaming support: ENABLED")

    app.run(
        host='0.0.0.0',
        port=PORT,
        debug=False,
        threaded=True
    )

