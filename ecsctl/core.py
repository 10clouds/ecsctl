import os

import oyaml as yaml
from pathlib import Path
from jsonpath_ng import parse
from jinja2 import Environment, FileSystemLoader
from jinja2.exceptions import TemplateNotFound
from jinja2.utils import open_if_exists
from . import template, exceptions


class FileLoader:
    file_types = ["*.yaml", "*.yml"]

    def __init__(self, file_path):
        self.file_path = file_path

    def load_raw_data(self):
        files = []
        path = Path(self.file_path)
        if path.is_dir():
            for f_type in self.file_types:
                files.extend([x for x in path.glob(f_type)])
            file_data = ""
            for item in files:
                f = item.read_text()
                if not f.startswith('---'):
                    file_data += '---\n'
                file_data += f
        else:
            file_data = path.read_text()
        return file_data

    def load(self):
        file_data = self.load_raw_data()
        return yaml.load_all(file_data, Loader=yaml.Loader)


class FileLoaderTemplate(FileLoader):
    class JinjaLoader(FileSystemLoader):
        def split_template_path(self, template):
            # based on https://github.com/pallets/jinja/blob/ca8b0b0287e320fe1f4a74f36910ef7ae3303d99/src/jinja2/loaders.py#L19
            pieces = []
            for piece in template.split("/"):
                if piece and piece != ".":
                    pieces.append(piece)
            return pieces

        def get_source(self, environment, template):
            # based on https://github.com/pallets/jinja/blob/ca8b0b0287e320fe1f4a74f36910ef7ae3303d99/src/jinja2/loaders.py#L174
            pieces = self.split_template_path(template)
            for searchpath in self.searchpath:
                filename = os.path.join(searchpath, *pieces)
                f = open_if_exists(filename)
                if f is None:
                    continue
                try:
                    contents = f.read().decode(self.encoding)
                finally:
                    f.close()

                mtime = os.path.getmtime(filename)

                def uptodate():
                    try:
                        return os.path.getmtime(filename) == mtime
                    except OSError:
                        return False

                return contents, filename, uptodate
            raise TemplateNotFound(template)

    file_types = ["*.tpl"]

    def __init__(self, file_path, envs, env_file):
        super(FileLoaderTemplate, self).__init__(file_path)
        self.envs = envs
        self.env_file = env_file
        self.base_dir = os.path.dirname(os.path.realpath(file_path))

    def load_raw_data(self):
        file_data = super(FileLoaderTemplate, self).load_raw_data()
        return self.render(file_data)

    def render(self, file_data):
        obj_env = FileLoaderEnvs(self.env_file)
        data = obj_env.load()
        for env in self.envs:
            k, v = env.split('=')
            data[k] = v
        return Environment(loader=self.JinjaLoader(self.base_dir)).from_string(str(file_data)).render(data)


class FileLoaderEnvs:
    file_types = ["*.env"]

    def __init__(self, files_path):
        self.files_path = files_path
        self.envs = {}

    def _get_vars(self, item):
        for line in item.read_text().split('\n'):
            if line:
                _key, *_value = line.split('=')
                self.envs[_key] = '='.join(_value)

    def load(self):
        for file_path in self.files_path:
            files, path = [], Path(file_path)
            if path.is_dir():
                for f_type in self.file_types:
                    files.extend([x for x in path.glob(f_type)])
                for item in files:
                    self._get_vars(item)
            else:
                self._get_vars(path)
        return self.envs



class ObjectType:
    __name = parse('metadata.name')
    __tags = parse('metadata.tags')
    __kind = parse('kind')
    __spec = parse('spec')
    __api = parse('apiVersion')

    def __init__(self, cluster, item):
        self.item = item
        self.cluster = cluster
        self.kind = None
        self.name = None
        self.spec = None
        self.tags = None
        self.ID = None
        self.template = None
        self._load_data()

    def _load_data(self):
        self.kind = self._get_value(self.__kind.find(self.item), 'name')
        self.name = self._get_value(self.__name.find(self.item), 'kind')
        self.spec = self._get_value(self.__spec.find(self.item), 'spec')
        self.tags = self.__tags.find(self.item)[0].value if self.__tags.find(self.item) else []
        metadata = self.item.get('metadata')
        metadata.pop('name', None)
        self.metadata = metadata
        self.ID = "{}: {}".format(self.kind, self.name)
        if self._get_value(self.__api.find(self.item), 'apiVersion') != 'v1':
            raise exceptions.ObjectTypeException('Currently we support only `apiVersion: v1`')

    @staticmethod
    def _get_value(found_elements, kind):
        try:
            return found_elements[0].value
        except IndexError:
            raise exceptions.ObjectTypeException('`{}` - this value doesn\'t exist.'.format(kind))

    def get_template(self):
        func = getattr(template, self.kind)
        self.template = func(
            name=self.name,
            tags=self.tags,
            yaml=self.spec,
            cluster=self.cluster,
            metadata=self.metadata)
        return self.template

    def show_response(self, resp):
        if not self.template:
            self.get_template()
        return self._get_value(parse(self.template.response).find(resp), self.template.response)
