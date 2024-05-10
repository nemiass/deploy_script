from fabric import Connection, Config
import subprocess
import os
import tarfile
import argparse
from datetime import datetime
from pathlib import Path
import time
import json
from termcolor import cprint

PATH_SCRIPT = Path(__file__).resolve().parent

def load_config():
    with open(f"{PATH_SCRIPT}/config.json", encoding="utf-8") as f:
        return json.load(f)


def search_jar(path):
    cprint(f"Buscando archivo jar en {path}...", "yellow")
    for root, dirs, files in os.walk(path):
        cprint(f"root: {root}", "yellow")
        for file in files:
            if file.endswith(".jar"):
                cprint(f"Archivo compilado encontrado: {file}", "green")
                return os.path.join(root, file)
    return None

def get_file_name_compress(name, module):
    now = datetime.now().strftime("%d-%m-%Y")
    module_name = "be" if module == "back" else "fe"
    return f"{module_name}_{name}_{now}.tar.gz"


def compilation_project(project, module, server):
    cprint(f"Compilando proyecto {project['name']} {module=}...", "yellow")
    if module == "back":
        commands = ["mvn", "clean", "package"]
    elif module == "front":
        _commands = {
            "dev": ["ng", "build", "--configuration=dev"],
            "uat": ["ng", "build", "--configuration=uat"],
        }
        commands = _commands.get(server, None)
    cprint(f"Comando: {' '.join(commands)}", "yellow")
    project_path = project["path"]
    res = subprocess.run(commands, cwd=project_path, shell=True)
    if res.returncode != 0:
        cprint("Error en el proceso de compilación", "red")
        exit(1)
    else:
        cprint("Proyecto compilado correctamente", "green")


def compress_project(project_data, module):
    cprint(f"Comprimiendo proyecto {project_data['name']} {module=}...", "yellow")
    source_path = ""
    project_name = project_data["name"]
    path_compilation = project_data["path_compilation"]
    now = datetime.now().strftime("%d-%m-%Y")
    if module == "back":
        path_jar_file = search_jar(path_compilation)
        if not path_jar_file:
            cprint(f"No se encontró el archivo jar en {path_compilation}", "red")
            exit(1)
        new_name = f"{project_name}_{now}.jar"
        new_path = os.path.join(os.path.dirname(path_jar_file), new_name)
        os.rename(path_jar_file, new_path)
        source_path = new_path
    elif module == "front":
        source_path = path_compilation

    compressed_file_name = get_file_name_compress(project_name, module)
    with tarfile.open(f"{PATH_SCRIPT}/{compressed_file_name}", "w:gz") as tar:
        if os.path.isdir(source_path):
            for root, _, files in os.walk(source_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    tar.add(file_path, arcname=os.path.relpath(file_path, source_path))
        else:
            tar.add(source_path, arcname=os.path.basename(source_path))
    cprint(f"Proyecto comprimido con éxito: {compressed_file_name}", "green")
    return compressed_file_name



def upload_compress_file(file_name_compress, project, module, credentials):
    #config = Config(overrides={"sudo": {"password": credentials["password"]}})
    host = credentials["ip"]
    user = credentials["user"]
    password = credentials["password"]
    name = project["name"]
    server = f"{credentials['server_name']}-{host}"
    cprint(f"Conectando al servidor {server}...", "yellow")
    with Connection(host, user, connect_kwargs={"password": password}) as conn:
        with conn.cd(project["path_server"]):
            # upload compile file
            cprint(f"Subiendo archivo: {file_name_compress} - ruta: {project['path_server']}", "yellow")
            conn.put(f"{PATH_SCRIPT}/{file_name_compress}", project["path_server"])
            cprint(f"Archivo {file_name_compress}  subido con éxito", "green")
            conn.run("ls")
            time.sleep(1)
            if module == "back":
                project_service = project["service_server"]
                cprint(f"Descomprimiendo archivo... {file_name_compress}", "yellow")
                conn.run(f"tar -xzf {file_name_compress}", hide=True)
                cprint("Archivos descomprimido con éxito", "green")
                conn.run("ls")
                time.sleep(1)
                # stop process and delete jar
                #conn.run("systemctl status nomina.service")
                cprint(f"Determinando proceso {project_service}...", "yellow")
                conn.run(f"systemctl stop {project_service}")
                cprint(f"Eliminando archivo jar... {name}.jar", "yellow")
                conn.run(f"rm -f {name}.jar")
                file_name_datetime = file_name_compress.split(".")[0].replace("be_", "")
                # rename descompress jar to nomina.jar
                cprint(f"Renombrando archivo descomprimido... {file_name_datetime}.jar --> {name}.jar", "yellow")
                conn.run(f"mv {file_name_datetime}.jar {name}.jar")
                # execution permission to nomina.jar
                cprint(f"Dando permisos de ejecución al archivo jar...  {name}.jar", "yellow")
                conn.run(f"chmod +x {name}.jar")
                # start process
                cprint(f"Iniciando proceso {project_service}...", "yellow")
                conn.run(f"systemctl start {project_service}")
                # view status and quit control + c
                res = conn.run(f"systemctl status {project_service}", pty=False)
                print(res.stdout)
            if module == "front":
                cprint(f"Proceso de eliminación de archivos anteriores... de la carpeta de despliegue front {project['path_server']}", "yellow")
                pwd_stdout = conn.run("pwd", hide=True).stdout
                cprint(f"Confirmar eliminación de archivos, dentro de: {pwd_stdout.strip()} y/n", "yellow")
                confirmation = input("y/n: ")
                if confirmation == "y":
                    res = conn.run("pwd", hide=True)
                    if pwd_stdout.strip() == project["path_server"]:
                        # delete except filename_compress
                        conn.run(f"ls | grep -v {file_name_compress} | xargs rm -rf")
                        #conn.run("rm -rf *")
                        cprint("Archivos eliminados con éxito", "green")
                conn.run("ls")
                cprint(f"Descomprimiendo archivo... {file_name_compress}", "yellow")
                conn.run(f"tar -xzf {file_name_compress}", hide=True)
                cprint("Archivo descomprimido con éxito", "green")
                cprint("Eliminando archivo comprimido...", "yellow")
                conn.run(f"rm -f {file_name_compress}")
                conn.run("ls")
    cprint("Archivo subido y ejecutado con éxito".upper(), "green")

def main():
    parser = argparse.ArgumentParser(description="Deploy script")
    parser.add_argument("project", type=str, help="Project to deploy, project name")
    parser.add_argument("module", type=str, help="Module to deploy, back or front")
    parser.add_argument("server", type=str, help="Server to deploy, uat or dev")

    args = parser.parse_args()
    project_name = args.project
    module = args.module
    server = args.server

    config = load_config()
    os.environ["JAVA_HOME"] = config["JAVA_HOME"]
    project_data = config["PROJECTS"][project_name][module]

    file_name = get_file_name_compress(project_data["name"], module)

    if not os.path.exists(f"{PATH_SCRIPT}/{file_name}"):
        compilation_project(project_data, module, server)
        file_name = compress_project(project_data, module)

    crendentials = config["SSH_CREDENTIALS"][server]
    upload_compress_file(file_name, project_data, module, crendentials)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        cprint(f"Error: {e}", "red")
        exit(1)
