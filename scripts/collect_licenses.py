import importlib.metadata
import shutil
import sys
from pathlib import Path


def main():
    destination=Path(sys.argv[1]);destination.mkdir(parents=True,exist_ok=True)
    count=0
    for dist in importlib.metadata.distributions():
        name=dist.metadata.get('Name','unknown')
        target=destination/(name+'-'+dist.version)
        target.mkdir(exist_ok=True)
        metadata=dist.read_text('METADATA')
        if metadata:(target/'METADATA.txt').write_text(metadata,encoding='utf-8')
        for file in dist.files or []:
            if any(word in str(file).lower() for word in ('license','copying','notice')):
                origin=Path(dist.locate_file(file))
                if origin.is_file():
                    clean=Path(*[p for p in Path(file).parts if p not in ('..','.')])
                    output=target/clean;output.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(origin,output);count+=1
    python=Path(sys.base_prefix)/'LICENSE_PYTHON.txt'
    if python.exists():shutil.copy2(python,destination/'LICENSE_PYTHON.txt')
    print('Python dependency license files:',count)


if __name__=='__main__':main()
