"""Credential persistence, isolation, migration and explicit recovery."""
import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from omegaconf import OmegaConf

from ms_agent.config.secrets import (PREFIX, SecretError, SecretStore,
                                     clear_secrets, contains_ciphertext,
                                     migrate_file, migrate_project,
                                     protect_config, reset_credentials,
                                     resolve_secret, subprocess_env,
                                     write_managed_config)


def test_unopened_known_projects_migrate_and_prevent_new_master_after_loss(
        home):
    from ms_agent.config.secrets import migrate_home
    from ms_agent.project.manager import ProjectManager
    manager = ProjectManager(str(home))
    project = manager.create('unopened')
    path = Path(project.path) / '.ms_agent' / 'config.yaml'
    path.write_text('llm:\n  api_key: unopened-credential\n')
    migrate_home(home)
    assert 'unopened-credential' not in path.read_text()
    assert 'enc:v1:' in path.read_text()
    SecretStore(home).key_file.unlink()
    with pytest.raises(SecretError):
        SecretStore(home).encrypt('replacement')
    reset_credentials(home, confirm=True)
    assert 'enc:' not in path.read_text()
    SecretStore(home).encrypt('replacement')


@pytest.fixture
def home(tmp_path, monkeypatch):
    directory = tmp_path / 'home'
    monkeypatch.setenv('MS_AGENT_HOME', str(directory))
    monkeypatch.delenv('MS_AGENT_SECRET_KEY', raising=False)
    monkeypatch.delenv('MS_AGENT_SECRET_KEY_FILE', raising=False)
    return directory


def test_registered_custom_field_protects_and_clears(home, monkeypatch):
    import ms_agent.config.secrets as secrets
    monkeypatch.setattr(secrets, '_FIELDS', set(secrets._FIELDS))
    secrets.register_secret_field('tools.custom.access_token')
    original = {'tools': {'custom': {'access_token': 'custom-secret'}}}
    protected = protect_config(original, home=home)
    value = protected['tools']['custom']['access_token']
    assert value.startswith(PREFIX)
    assert resolve_secret(value, home=home) == 'custom-secret'
    assert clear_secrets(protected)['tools']['custom']['access_token'] == ''
    assert original['tools']['custom']['access_token'] == 'custom-secret'


def test_unwritable_master_location_never_falls_back_into_home(home):
    (home.parent / 'home.secrets').write_text('not a directory')
    with pytest.raises(SecretError):
        write_managed_config(
            home / 'settings.json', {'llm': {
                'api_key': 'credential'
            }},
            home=home)
    assert not (home / 'settings.json').exists()
    assert not (home / 'master.key').exists()


def test_failed_atomic_migration_keeps_original_file(home, monkeypatch):
    import ms_agent.config.secrets as secrets
    home.mkdir()
    path = home / 'settings.json'
    path.write_text(json.dumps({'llm': {'api_key': 'legacy-secret'}}))
    before = path.read_bytes()

    def fail(*args, **kwargs):
        raise OSError('Simulated disk write failure')

    monkeypatch.setattr(secrets, 'atomic_write_json', fail)
    with pytest.raises(OSError):
        migrate_file(path, home=home)
    assert path.read_bytes() == before
    assert not list(home.glob('*.bak'))


def test_roundtrip_and_independent_key_permissions(home):
    store = SecretStore(home)
    value = store.encrypt('synthetic-provider-secret')
    assert value.startswith(PREFIX)
    assert 'synthetic-provider-secret' not in value
    assert store.decrypt(value) == 'synthetic-provider-secret'
    assert store.key_file == home.parent / 'home.secrets' / 'master.key'
    assert not store.key_file.is_relative_to(home)
    if os.name != 'nt':
        assert stat.S_IMODE(store.key_file.stat().st_mode) == 0o600
        assert stat.S_IMODE(store.key_file.parent.stat().st_mode) == 0o700


def test_home_aliases_use_same_key(home):
    home.mkdir()
    alias = home.parent / 'alias'
    alias.symlink_to(home, target_is_directory=True)
    first = SecretStore(str(home) + '/')
    cipher = first.encrypt('credential')
    assert SecretStore(alias).key_file == first.key_file
    assert SecretStore(alias).decrypt(cipher) == 'credential'


def test_default_key_directory_symlink_is_rejected_even_if_key_exists(home):
    other = home.parent / 'other-secrets'
    other.mkdir()
    (other / 'master.key').write_bytes(Fernet.generate_key())
    (home.parent / 'home.secrets').symlink_to(other, target_is_directory=True)
    store = SecretStore(home)
    with pytest.raises(SecretError):
        store.encrypt('credential')
    assert store.fingerprint() == 'unavailable'


def test_concurrent_initialization_uses_one_master(home):
    with ThreadPoolExecutor(max_workers=8) as executor:
        values = list(
            executor.map(lambda _: SecretStore(home).encrypt('credential'),
                         range(16)))
    assert all(
        SecretStore(home).decrypt(value) == 'credential' for value in values)


def test_wrong_home_does_not_decrypt_or_create_key(home):
    value = SecretStore(home).encrypt('credential')
    other = SecretStore(home.parent / 'other')
    with pytest.raises(SecretError):
        other.decrypt(value)
    assert not other.key_file.exists()
    other.encrypt('other credential')
    with pytest.raises(SecretError):
        other.decrypt(value)


def test_missing_key_blocks_replacement_until_explicit_reset(home):
    path = home / 'settings.json'
    write_managed_config(
        path, {'providers': {
            'x': {
                'api_key': 'credential',
                'models': ['m']
            }
        }},
        home=home)
    original = path.read_bytes()
    SecretStore(home).key_file.unlink()
    with pytest.raises(SecretError):
        write_managed_config(
            path, {'providers': {
                'x': {
                    'api_key': 'replacement'
                }
            }}, home=home)
    assert path.read_bytes() == original
    assert not SecretStore(home).key_file.exists()
    data = json.loads(original)
    data['theme'] = 'dark'
    write_managed_config(path, data, home=home)
    assert not SecretStore(home).key_file.exists()
    assert SecretStore(home).view(
        data['providers']['x']['api_key']) == ('unavailable', '')
    with pytest.raises(SecretError):
        reset_credentials(home)
    reset_credentials(home, confirm=True)
    data = json.loads(path.read_text())
    assert data['theme'] == 'dark'
    assert data['providers']['x']['models'] == ['m']
    data['providers']['x']['api_key'] = 'replacement'
    write_managed_config(path, data, home=home)
    assert SecretStore(home).decrypt(
        json.loads(
            path.read_text())['providers']['x']['api_key']) == 'replacement'


@pytest.mark.parametrize('value', ['enc:v2:abc', 'enc:v1:', 'enc:v1:invalid'])
def test_invalid_ciphertext_never_becomes_a_key(home, value):
    SecretStore(home).encrypt('initialize')
    with pytest.raises(SecretError):
        resolve_secret(value, home=home)
    assert SecretStore(home).view(value) == ('unavailable', '')


def test_external_key_modes_do_not_copy_key(home, monkeypatch, tmp_path):
    key = Fernet.generate_key()
    external = tmp_path / 'external-key'
    external.write_bytes(key)
    monkeypatch.setenv('MS_AGENT_SECRET_KEY_FILE', str(external))
    value = SecretStore(home).encrypt('credential')
    assert SecretStore(home).decrypt(value) == 'credential'
    assert not (home.parent / 'home.secrets').exists()
    monkeypatch.delenv('MS_AGENT_SECRET_KEY_FILE')
    monkeypatch.setenv('MS_AGENT_SECRET_KEY', key.decode())
    assert SecretStore(home).decrypt(value) == 'credential'
    assert not (home.parent / 'home.secrets').exists()


@pytest.mark.parametrize('value', ['', 'wrong', '非法钥匙'])
def test_invalid_explicit_key_never_falls_back(home, monkeypatch, value):
    monkeypatch.setenv('MS_AGENT_SECRET_KEY', value)
    with pytest.raises(SecretError):
        SecretStore(home).encrypt('credential')
    assert not (home.parent / 'home.secrets').exists()


def test_ambiguous_and_missing_external_sources_fail(home, monkeypatch):
    monkeypatch.setenv('MS_AGENT_SECRET_KEY_FILE', str(home / 'missing'))
    with pytest.raises(SecretError):
        SecretStore(home).encrypt('credential')
    monkeypatch.setenv('MS_AGENT_SECRET_KEY', Fernet.generate_key().decode())
    with pytest.raises(SecretError):
        SecretStore(home)


def test_field_registry_preserves_other_content_and_runtime_object(home):
    config = OmegaConf.create({
        'llm': {
            'api_key': 'model-secret'
        },
        'tools': {
            'web_search': {
                'exa_api_keys': ['a', 'b']
            },
            'custom': {
                'key': 'unchanged'
            }
        },
        'memory': {
            'unified_memory': {
                'mem0': {
                    'llm': {
                        'config': {
                            'api_key': 'fact-secret'
                        }
                    },
                    'embedder': {
                        'config': {
                            'api_key': 'embed-secret'
                        }
                    },
                }
            }
        },
        'prompt': {
            'system': 'ordinary prompt'
        },
    })
    data = protect_config(config, home=home)
    assert config.llm.api_key == 'model-secret'
    assert data['llm']['api_key'].startswith(PREFIX)
    assert data['memory']['unified_memory']['mem0']['llm']['config'][
        'api_key'].startswith(PREFIX)
    assert data['memory']['unified_memory']['mem0']['embedder']['config'][
        'api_key'].startswith(PREFIX)
    assert resolve_secret(
        data['tools']['web_search']['exa_api_keys'], home=home) == ['a', 'b']
    assert data['tools']['custom']['key'] == 'unchanged'
    assert data['prompt']['system'] == 'ordinary prompt'
    assert protect_config(data, home=home) == data


def test_migration_is_idempotent_and_does_not_make_backups(home):
    home.mkdir()
    path = home / 'settings.json'
    path.write_text(
        json.dumps({
            'llm': {
                'api_key': 'legacy-secret'
            },
            'theme': 'dark'
        }))
    assert migrate_file(path, home=home)
    first = path.read_bytes()
    assert b'legacy-secret' not in first
    assert not migrate_file(path, home=home)
    assert path.read_bytes() == first
    assert not list(home.glob('*.bak'))


def test_project_migration_covers_legacy_local_and_history_only(
        home, tmp_path):
    project = tmp_path / 'project'
    for name in ('.ms_agent/config.yaml', '.ms-agent/config.yaml',
                 '.ms_agent/memory/agent.yaml'):
        path = project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('llm:\n  api_key: project-secret\n')
    local = project / '.ms_agent/settings.local.json'
    local.write_text(
        json.dumps({'providers': {
            'p': {
                'api_key': 'local-secret'
            }
        }}))
    source = project / 'agent.yaml'
    source.write_text('llm:\n  api_key: handwritten-source\n')
    messages = project / '.ms_agent/memory/agent.json'
    messages.write_text('[{"role":"user","content":"hello"}]')
    migrate_project(project, home=home)
    for name in ('.ms_agent/config.yaml', '.ms-agent/config.yaml',
                 '.ms_agent/memory/agent.yaml'):
        assert 'project-secret' not in (project / name).read_text()
    assert 'local-secret' not in local.read_text()
    assert 'handwritten-source' in source.read_text()
    assert 'hello' in messages.read_text()
    reset_credentials(home, projects=[project], confirm=True)
    assert not contains_ciphertext(
        OmegaConf.load(project / '.ms_agent/config.yaml'))
    assert 'hello' in messages.read_text()


def test_environment_references_and_nonsecret_interpolations_are_preserved(
        home):
    config = OmegaConf.create({
        'llm': {
            'api_key': '${oc.env:EXAMPLE_KEY}'
        },
        'tools': {
            'web_search': {
                'exa_api_keys': ['${oc.env:EXAMPLE_KEY}']
            },
            'custom': {
                'env': {
                    'TOKEN': '${UNKNOWN}'
                }
            }
        }
    })
    data = protect_config(config, home=home)
    assert data['llm']['api_key'] == '${oc.env:EXAMPLE_KEY}'
    assert data['tools']['web_search']['exa_api_keys'] == [
        '${oc.env:EXAMPLE_KEY}'
    ]
    assert data['tools']['custom']['env']['TOKEN'] == '${UNKNOWN}'
    assert not SecretStore(home).key_file.exists()


def test_malformed_unopened_project_does_not_block_other_migrations(home):
    from ms_agent.config.secrets import migrate_home
    from ms_agent.project.manager import ProjectManager
    manager = ProjectManager(str(home))
    SecretStore(home).encrypt('initial')
    broken = manager.create('broken')
    healthy = manager.create('healthy')
    bad_path = Path(broken.path) / '.ms_agent/config.yaml'
    good_path = Path(healthy.path) / '.ms_agent/config.yaml'
    bad_path.write_text('llm: [broken-sensitive-value')
    good_path.write_text('llm:\n  api_key: healthy-sensitive-value\n')
    with pytest.raises(SecretError) as error:
        migrate_home(home)
    assert 'broken-sensitive-value' not in str(error.value)
    assert 'healthy-sensitive-value' not in good_path.read_text()
    assert bad_path.read_text() == 'llm: [broken-sensitive-value'


def test_omegaconf_secret_list_is_resolved(home):
    cipher = SecretStore(home).encrypt('credential')
    values = OmegaConf.create([cipher])
    assert resolve_secret(values, home=home) == ['credential']


def test_clear_and_child_environments_never_carry_master(home):
    data = clear_secrets({
        'providers': {
            'p': {
                'api_key': 'enc:v1:old',
                'models': ['m']
            }
        },
        '_secret_home': '/source/home'
    })
    assert data == {'providers': {'p': {'api_key': '', 'models': ['m']}}}
    assert subprocess_env({
        'MS_AGENT_SECRET_KEY': 'private',
        'MS_AGENT_SECRET_KEY_FILE': '/key',
        'PATH': '/bin',
        'MS_AGENT_HOME': str(home)
    }) == {
        'PATH': '/bin',
        'MS_AGENT_HOME': str(home)
    }


def test_new_settings_writers_preserve_encryption_and_fail_after_key_loss(home):
    from ms_agent.config.interaction_settings import InteractionSettings
    from ms_agent.config.search_settings import SearchSettingsManager
    path = home / 'settings.json'
    home.mkdir()
    path.write_text(json.dumps({'providers': {'vendor': {'api_key': 'legacy-key'}}}))
    InteractionSettings(home).update('steer')
    search = SearchSettingsManager(home)
    search.set_api_key('search-key', 'exa')
    data = json.loads(path.read_text())
    assert data['providers']['vendor']['api_key'].startswith(PREFIX)
    assert data['tools']['web_search']['exa_api_key'].startswith(PREFIX)
    search.set_engine('exa')
    assert search.get().has_key
    SecretStore(home).key_file.unlink()
    assert not search.get().has_key
    before = path.read_bytes()
    with pytest.raises(SecretError):
        search.set_api_key('replacement')
    assert path.read_bytes() == before


def test_tui_discovery_decrypts_and_never_falls_back_after_key_loss(home, monkeypatch):
    from ms_agent.command.builtin.config_cmds import _effective_api_key
    value = SecretStore(home).encrypt('catalog-key')
    assert _effective_api_key('openai', {'api_key': value}) == 'catalog-key'
    SecretStore(home).key_file.unlink()
    monkeypatch.setenv('OPENAI_API_KEY', 'unrelated-key')
    with pytest.raises(SecretError):
        _effective_api_key('openai', {'api_key': value})


def test_tui_credential_update_clears_legacy_duplicate_and_cross_provider_key(home):
    from ms_agent.config.model_settings import ModelSettingsManager
    home.mkdir()
    path = home / 'settings.json'
    path.write_text(json.dumps({'llm': {'provider': 'a', 'model': 'm',
                                     'api_key': 'retired-key', 'base_url': 'https://a.invalid'}}))
    manager = ModelSettingsManager(home)
    manager.patch_provider('a', api_key='current-key')
    assert 'api_key' not in manager._load_raw()['llm']
    manager.patch_provider('a', clear_api_key=True)
    assert 'api_key' not in manager._load_raw()['llm']
    manager.set_default_model('n', 'b')
    assert 'base_url' not in manager._load_raw()['llm']


def test_new_history_clears_registered_fields_without_mutating_runtime(home, tmp_path):
    from ms_agent.llm.utils import Message
    from ms_agent.utils.constants import DEFAULT_MEMORY_DIR
    from ms_agent.utils.utils import save_history
    config = OmegaConf.create({'llm': {'api_key': 'runtime-key'},
                               'tools': {'web_search': {'exa_api_keys': ['search-key']}}})
    save_history(str(tmp_path / 'project'), 'agent', config, [Message(role='user', content='hello')])
    path = tmp_path / 'project' / DEFAULT_MEMORY_DIR / 'agent.yaml'
    saved = OmegaConf.load(path)
    assert saved.llm.api_key == ''
    assert saved.tools.web_search.exa_api_keys == []
    assert config.llm.api_key == 'runtime-key'
    assert not SecretStore(home).key_file.exists()
