#!/usr/bin/env python3

import json
import os
import shutil
import subprocess
from urllib.request import Request, urlopen
import urllib.parse

import gitignore_parser

import changelog_creator
import modlist

from config import repo, repo_owner, modpack_name

MOD_LIST_CREATOR_VERSION = '1.1.5'


def main():
    with open('tokens.json') as file:
        token = json.loads(file.read())['github']

    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode('utf-8').strip()

    with open('pack.json') as file:
        manifest = json.loads(file.read())

    print(f'Prepare Release v{manifest["version"]} on commit {commit}')

    print('Delete old build data')
    if os.path.isdir('build'):
        shutil.rmtree('build')
    os.makedirs('build')

    print('Read gitignore')
    gitignore = gitignore_parser.parse_gitignore('.gitignore', '.')

    print('Generate manifest')
    modlist.generateManifest()
    with open('manifest.json') as file:
        manifest = json.loads(file.read())

    print('Creating changelog')
    changelog_creator.main(manifest)

    print('Download ModListCreator')
    request = Request(
        f'https://github.com/MelanX/ModListCreator/releases/download/v{MOD_LIST_CREATOR_VERSION}/ModListCreator-{MOD_LIST_CREATOR_VERSION}.jar'
    )
    response = urlopen(request)
    with open(os.path.join('build', 'ModListCreator.jar'), mode='wb') as file:
        file.write(response.read())

    print('Update root directory modlist.')
    subprocess.check_call(
        ['java', '-jar', os.path.join('build', 'ModListCreator.jar'),
         '--md',
         '--manifest', 'manifest.json',
         '--output', '.',
         '--detailed']
    )

    print('Create empty overrides folder.')
    target_dir = os.path.join('build', 'overrides')
    if os.path.isdir(target_dir):
        shutil.rmtree(target_dir)

    os.makedirs(target_dir)

    print('Prepare CurseForge pack.')
    createModpackZip(manifest, gitignore)

    print('Prepare Server zip.')
    createServerZip(manifest, gitignore)

    print('Uploading to GitHub')
    uploadToGithub(token, manifest)

    print('Done')


def createModpackZip(manifest, gitignore):
    targetDir = os.path.join('build', 'curseforge')

    os.makedirs(targetDir)
    shutil.copy2('manifest.json', targetDir + os.path.sep + 'manifest.json')

    print('Generate ModList')
    subprocess.check_call(
        ['java', '-jar', os.path.join('build', 'ModListCreator.jar'),
         '--html',
         '--manifest', targetDir + os.path.sep + 'manifest.json',
         '--output', targetDir]
    )

    print('Copy overrides')
    with open('overrides.txt') as file:
        overrides = [x.strip() for x in file.read().split('\n')]
    shutil.copytree(os.path.join('build', 'overrides'), targetDir + os.path.sep + manifest['overrides'])
    for entry in overrides:
        copyNotGitignoreTree('.', targetDir + os.path.sep + manifest['overrides'], entry, gitignore)

    print('Create archive')
    shutil.make_archive(os.path.join('build', 'curseforge'), 'zip', targetDir)


def createServerZip(manifest, gitignore):
    targetDir = os.path.join('build', 'server')

    os.makedirs(targetDir)

    print('Create server ModList')
    clientmods = []
    with open('clientmods.txt') as file:
        if file.read() != "":
            clientmods = [int(x.strip()) for x in file.read().split('\n')]
    with open(targetDir + os.path.sep + 'server.txt', mode='w') as file:
        mcv = manifest['minecraft']['version']
        mlv: str = manifest['minecraft']['modLoaders'][0]['id']
        if mlv.startswith('forge-'):
            mlv = mlv[6:]
        file.write(f'{mcv}/{mlv}\n')
        for mod in manifest['files']:
            if not mod['projectID'] in clientmods:
                file.write(f'{mod["projectID"]}/{mod["fileID"]}\n')

    print('Copy server files')
    shutil.copytree('serverdata', targetDir, dirs_exist_ok=True)

    print('Copy overrides')
    with open('overrides.txt') as file:
        overrides = [x.strip() for x in file.read().split('\n')]
    shutil.copytree(os.path.join('build', 'overrides'), targetDir, dirs_exist_ok=True)
    for entry in overrides:
        copyNotGitignoreTree('.', targetDir, entry, gitignore)

    print('Generate server files')
    with open(targetDir + os.path.sep + 'server.properties', mode='w') as f:
        f.writelines([
            'allow-flight=true\n',
            'enable-command-block=true\n',
            'max-players=32\n',
            f'motd=§{modpack_name}\\nv{manifest["version"]}§r',
            'online-mode=true\n',
            'spawn-protection=0\n',
            'view-distance=8\n'
        ])

    print('Create archive')
    shutil.make_archive(os.path.join('build', 'server'), 'zip', targetDir)


def copyNotGitignoreTree(sourceBase: str, targetBase: str, relative: str, gitignore):
    source = sourceBase + os.path.sep + relative
    target = targetBase + os.path.sep + relative
    if os.path.isdir(source):
        for child in os.listdir(source):
            copyNotGitignoreTree(sourceBase, targetBase, relative + os.path.sep + child, gitignore)
    else:
        if not gitignore(relative):
            if not os.path.isdir(os.path.dirname(target)):
                os.makedirs(os.path.dirname(target))
            shutil.copy2(source, target)


def uploadToGithub(token, manifest):
    print('Push latest changes to GitHub')
    subprocess.check_call(['git', 'add', '.'])
    subprocess.check_call(['git', 'commit', '-m', f'v{manifest["version"]} release'])
    subprocess.check_call(['git', 'push'])
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode('utf-8').strip()

    print(f'Create release on newer commit {commit}')
    create_release = Request(f'https://api.github.com/repos/{repo_owner}/{repo}/releases',
                             method='POST')
    create_release.add_header('Authorization', f'token {token}')
    create_release.add_header('Accept', 'application/vnd.github.v3+json')
    create_release.add_header('Content-Type', 'application/json')
    with open(f'changelogs/changelog-{manifest["version"]}.md', 'r', encoding='utf-8') as file:
        changelog = file.read()
    create_release.data = json.dumps({
        'tag_name': f'v{manifest["version"]}',
        'target_commitish': commit,
        'name': f'v{manifest["version"]}',
        'body': changelog,
        'prerelease': False
    }).encode('utf-8')
    release_id = json.loads(urlopen(create_release).read())['id']

    print('Upload CurseForge pack')
    uploadFileToRelease(token, release_id, manifest, 'application/zip', urllib.parse.quote(f'[Client] {modpack_name}'), 'zip',
                        os.path.join('build', 'curseforge.zip'))

    print('Upload Server zip')
    uploadFileToRelease(token, release_id, manifest, 'application/zip', urllib.parse.quote(f'[Server] {modpack_name}'), 'zip',
                        os.path.join('build', 'server.zip'))


def uploadFileToRelease(token, release_id, manifest, mime, basename, suffix, path):
    request = Request(
        f'https://uploads.github.com/repos/{repo_owner}/{repo}/releases/{release_id}/assets?name={basename}-v{manifest["version"]}.{suffix}',
        method='POST')
    request.add_header('Authorization', f'token {token}')
    request.add_header('Content-Type', mime)
    with open(path, mode='rb') as file:
        request.data = file.read()
    urlopen(request)


if __name__ == '__main__':
    main()
