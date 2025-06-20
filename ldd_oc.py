import web
import os
import json
from src.wl import WebLogger
import requests
import urllib.parse as urlparse
import re
import csv
from urllib.parse import parse_qs, unquote
from rdflib.plugins.sparql.parser import parseUpdate
import subprocess
import sys
import argparse
from io import StringIO
from src.ldd import LinkedDataDirector


# Load the configuration file
#test comment
with open("conf.json") as f:
    c = json.load(f)
    

# Docker ENV variables
env_config = {
    "base_url": os.getenv("BASE_URL", c["base_url"]),
    "log_dir": os.getenv("LOG_DIR", c["log_dir"]),
    "sparql_endpoint_index": os.getenv("SPARQL_ENDPOINT_INDEX", c["sparql_endpoint_index"]),
    "sparql_endpoint_meta": os.getenv("SPARQL_ENDPOINT_META", c["sparql_endpoint_meta"]),
    "index_base_url": os.getenv("INDEX_BASE_URL", c["index_base_url"]),
    "sync_enabled": os.getenv("SYNC_ENABLED", "false").lower() == "true"
}


active = {
    "corpus": "datasets",
    "index": "datasets",
    "meta": "datasets",
    "coci": "datasets",
    "doci": "datasets",
    "poci": "datasets",
    "croci": "datasets",
    "ccc": "datasets",
    "oci": "tools",
    "intrepid": "tools",
    "api": "querying",
    "api": "querying",
    "search": "querying"
}

# URL Mapping
urls = (
    '/favicon.ico', 'Favicon',
    "/sparql/index", "SparqlIndex",
    "/sparql/meta", "SparqlMeta",
    "/index/(.*)?", "IndexContentNegotiation",
    "/meta/(../.+)", "MetaContentNegotiation"
    
)

# Set the web logger
web_logger = WebLogger(env_config["base_url"], env_config["log_dir"], [
    "HTTP_X_FORWARDED_FOR", # The IP address of the client
    "REMOTE_ADDR",          # The IP address of internal balancer
    "HTTP_USER_AGENT",      # The browser type of the visitor
    "HTTP_REFERER",         # The URL of the page that called your program
    "HTTP_HOST",            # The hostname of the page being attempted
    "REQUEST_URI",          # The interpreted pathname of the requested document
                            # or CGI (relative to the document root)
    "HTTP_AUTHORIZATION",   # Access token
    ],
    # comment this line only for test purposes
     {"REMOTE_ADDR": ["130.136.130.1", "130.136.2.47", "127.0.0.1"]}
)


render = web.template.render(c["html"], globals={
    'str': str,
    'isinstance': isinstance,
    'render': lambda *args, **kwargs: render(*args, **kwargs)
})

# App Web.py
app = web.application(urls, globals())



def sync_static_files():
    """
    Function to synchronize static files using sync_static.py
    """
    try:
        print("Starting static files synchronization...")
        subprocess.run([sys.executable, "sync_static.py", "--auto"], check=True)
        print("Static files synchronization completed")
    except subprocess.CalledProcessError as e:
        print(f"Error during static files synchronization: {e}")
    except Exception as e:
        print(f"Unexpected error during synchronization: {e}")



# Process favicon.ico requests
class Favicon:
    def GET(self): 
        raise web.seeother("/static/favicon.ico")

class Header:
    def GET(self):
        current_subdomain = web.ctx.host.split('.')[0].lower()
        return render.header(sp_title="", current_subdomain=current_subdomain)

class Sparql:
    def __init__(self, sparql_endpoint, sparql_endpoint_title, yasqe_sparql_endpoint):
        self.sparql_endpoint = sparql_endpoint
        self.sparql_endpoint_title = sparql_endpoint_title
        self.yasqe_sparql_endpoint = yasqe_sparql_endpoint
        self.collparam = ["query"]

    def GET(self):
        web_logger.mes()
        content_type = web.ctx.env.get('CONTENT_TYPE')
        return self.__run_query_string(self.sparql_endpoint_title, web.ctx.env.get("QUERY_STRING"), content_type)

    def POST(self):
        content_type = web.ctx.env.get('CONTENT_TYPE')
        cur_data = web.data().decode("utf-8")

        if "application/x-www-form-urlencoded" in content_type:
            return self.__run_query_string(active["sparql"], cur_data, True, content_type)
        elif "application/sparql-query" in content_type:
            isupdate = None
            isupdate, sanitizedQuery = self.__is_update_query(cur_data)
            if not isupdate:
                return self.__contact_tp(cur_data, True, content_type)
            else:
                raise web.HTTPError(
                    "403 ",
                    {"Content-Type": "text/plain"},
                    "SPARQL Update queries are not permitted."
                )
        else:
            raise web.redirect("/")

    def __contact_tp(self, data, is_post, content_type):
        accept = web.ctx.env.get('HTTP_ACCEPT')
        if accept is None or accept == "*/*" or accept == "":
            accept = "application/sparql-results+xml"
        if is_post:
            req = requests.post(self.sparql_endpoint, data=data,
                              headers={'content-type': content_type, "accept": accept})
        else:
            req = requests.get("%s?%s" % (self.sparql_endpoint, data),
                             headers={'content-type': content_type, "accept": accept})

        if req.status_code == 200:
            web.header('Access-Control-Allow-Origin', '*')
            web.header('Access-Control-Allow-Credentials', 'true')
            if req.headers["content-type"] == "application/json":
                web.header('Content-Type', 'application/sparql-results+json')
            else:
                web.header('Content-Type', req.headers["content-type"])
            web_logger.mes()
            req.encoding = "utf-8"
            return req.text
        else:
            raise web.HTTPError(
                str(req.status_code)+" ", {"Content-Type": req.headers["content-type"]}, req.text)

    def __is_update_query(self, query):
        query = re.sub(r'^\s*#.*$', '', query, flags=re.MULTILINE)
        query = '\n'.join(line for line in query.splitlines() if line.strip()) 
        try:
            parseUpdate(query)
            return True, 'UPDATE query not allowed'
        except Exception:
            return False, query

    def __run_query_string(self, active, query_string, is_post=False,
                          content_type="application/x-www-form-urlencoded"):
        # Add redirect if no query string is provided
        if query_string is None or query_string.strip() == "":
            raise web.seeother('/')
        
        parsed_query = urlparse.parse_qs(query_string)
        current_subdomain = web.ctx.host.split('.')[0].lower()

        for k in self.collparam:
            if k in parsed_query:
                query = parsed_query[k][0]
                isupdate = None
                isupdate, sanitizedQuery = self.__is_update_query(query)

                if isupdate != None:
                    if isupdate:
                        raise web.HTTPError(
                            "403 ",
                            {"Content-Type": "text/plain"},
                            "SPARQL Update queries are not permitted."
                        )
                    else:
                        return self.__contact_tp(query_string, is_post, content_type)

        raise web.HTTPError(
            "408",
            {"Content-Type": "text/plain"},
            "Not a valid request"
        )
    

class SparqlIndex(Sparql):
    def __init__(self):
        Sparql.__init__(self, env_config["sparql_endpoint_index"],
                       "index", "/sparql/index")

class SparqlMeta(Sparql):
    def __init__(self):
        Sparql.__init__(self, env_config["sparql_endpoint_meta"],
                       "meta", "/sparql/meta")

       

    def OPTIONS(self, dataset, call):
        # remember to remove the slash at the end
        org_ref = web.ctx.env.get('HTTP_REFERER')
        if org_ref is not None:
            org_ref = org_ref[:-1]
        else:
            org_ref = "*"

        web.header('Access-Control-Allow-Origin', org_ref)
        web.header('Access-Control-Allow-Credentials', 'true')
        web.header('Access-Control-Allow-Methods', '*')
        web.header('Access-Control-Allow-Headers', 'Authorization')

    def GET(self, dataset, call):
        man = None

        if dataset == "":
            raise web.redirect("/")

        elif dataset == "index":
            man = index_api_manager
            doc = index_doc_manager
            if "v2" in call:
                man = index_api_manager_v2
                doc = index_doc_manager_v2
        elif dataset == "meta":
            man = meta_api_manager
            doc = meta_doc_manager


        if man is None:
            raise web.notfound()
        else:
            if re.match("^/v[1-9]*/?$", call):
                # remember to remove the slash at the end
                org_ref = web.ctx.env.get('HTTP_REFERER')
                if org_ref is not None:
                    org_ref = org_ref[:-1]
                else:
                    org_ref = "*"

                web.header('Access-Control-Allow-Origin', org_ref)
                web.header('Access-Control-Allow-Credentials', 'true')
                web.header('Content-Type', "text/html")
                web.header('Access-Control-Allow-Methods', '*')
                web.header('Access-Control-Allow-Headers', 'Authorization')
                web_logger.mes()
                return doc.get_documentation()[1]
            else:
                content_type = web.ctx.env.get('HTTP_ACCEPT')
                if content_type is not None and "text/csv" in content_type:
                    content_type = "text/csv"
                else:
                    content_type = "application/json"

                operation_url = call + unquote(web.ctx.query)
                op = man.get_op(operation_url)

                if type(op) is Operation:
                    status_code, res, c_type = op.exec(
                        content_type=content_type)
                    if status_code == 200:
                        # remember to remove the slash at the end
                        org_ref = web.ctx.env.get('HTTP_REFERER')
                        if org_ref is not None:
                            org_ref = org_ref[:-1]
                        else:
                            org_ref = "*"

                        web.header('Access-Control-Allow-Origin', org_ref)
                        web.header('Access-Control-Allow-Credentials', 'true')
                        web.header('Content-Type', c_type)
                        web.header('Access-Control-Allow-Methods', '*')
                        web.header('Access-Control-Allow-Headers',
                                   'Authorization')
                        web_logger.mes()
                        return res
                    else:
                        try:
                            with StringIO(res) as f:
                                if content_type == "text/csv":
                                    mes = next(csv.reader(f))[0]
                                else:
                                    mes = json.dumps(
                                        next(csv.DictReader(f)), ensure_ascii=False)
                            raise web.HTTPError(
                                str(status_code)+" ", {"Content-Type": content_type}, mes)
                        except:
                            raise web.HTTPError(
                                str(status_code)+" ", {"Content-Type": content_type}, str(res))
                else:
                    raise web.HTTPError(
                        "404 ", {"Content-Type": content_type}, "No API operation found at URL '%s'" % call)

class ContentNegotiation:
    def __init__(self, base_url, local_url, context_path=None, from_triplestore=None, label_func=None):
        self.base_url = base_url
        self.local_url = local_url
        self.from_triplestore = from_triplestore
        self.label_func = label_func
        self.context_path = context_path

    def GET(self, file_path=None):
        ldd = LinkedDataDirector(
            c["index_base_path"], c["html"], self.base_url,
            self.context_path, self.local_url,
            label_conf=c["label_conf"], tmp_dir=c["tmp_dir"],
            dir_split_number=int(c["dir_split_number"]),
            file_split_number=int(c["file_split_number"]),
            default_dir=c["default_dir"], from_triplestore=self.from_triplestore,
            label_func=self.label_func)
        cur_page = ldd.redirect(file_path)
        if cur_page is None:
            raise web.notfound()
        else:
            web_logger.mes()
            return cur_page

class IndexContentNegotiation(ContentNegotiation):
    def __init__(self):
        ContentNegotiation.__init__(self, c["index_base_url"], c["index_local_url"],
                                    context_path=c["ocdm_json_context_path"],
                                    from_triplestore=c["sparql_endpoint_index"],
                                    label_func=lambda u: "oci:%s" % re.findall(
                                        "^.+/ci/(.+)$", u)[0]
                                    if "/ci/" in u else "provenance agent 1" if "/pa/1" in u
                                    else "INDEX")

class MetaContentNegotiation(ContentNegotiation):
    def __init__(self):
        ContentNegotiation.__init__(self, c["index_base_url"], c["meta_local_url"],
                                    context_path=c["ocdm_json_context_path"],
                                    from_triplestore=c["sparql_endpoint_meta"],
                                    label_func=lambda u: "%s %s" % re.findall("^.+/meta/(..)/(.+)$", u)[0])



# Run the application
if __name__ == "__main__":
    # Add startup log
    print("Starting API OpenCitations web application...")
    print(f"Configuration: Base URL={env_config['base_url']}")
    print(f"Sync enabled: {env_config['sync_enabled']}")

    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='API OpenCitations web application')
    parser.add_argument(
        '--sync-static',
        action='store_true',
        help='synchronize static files at startup (for local testing or development)'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=8080,
        help='port to run the application on (default: 8080)'
    )
    
    args = parser.parse_args()
    print(f"Starting on port: {args.port}")
    
    if args.sync_static or env_config["sync_enabled"]:
        # Run sync if either --sync-static is provided (local testing) 
        # or SYNC_ENABLED=true (Docker environment)
        print("Static sync is enabled")
        sync_static_files()
    else:
        print("Static sync is disabled")
    
    print("Starting web server...")
    # Set the port for web.py
    web.httpserver.runsimple(app.wsgifunc(), ("0.0.0.0", args.port))