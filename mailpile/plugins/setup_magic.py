import os
from gettext import gettext as _
from datetime import date

from mailpile.plugins import PluginManager
from mailpile.plugins import __all__ as PLUGINS
from mailpile.commands import Command
from mailpile.crypto.gpgi import GnuPG, SignatureInfo, EncryptionInfo
from mailpile.util import *
from mailpile.plugins.migrate import Migrate

from mailpile.plugins.tags import AddTag, Filter


_plugins = PluginManager(builtin=__file__)


##[ Commands ]################################################################

class Setup(Command):
    """Perform initial setup"""
    SYNOPSIS = (None, 'setup', None, None)
    ORDER = ('Internals', 0)
    LOG_PROGRESS = True

    TAGS = {
        'New': {
            'type': 'unread',
            'label': False,
            'display': 'invisible',
            'icon': 'icon-new',
            'label_color': '03-gray-dark',
            'name': _('New'),
        },
        'Inbox': {
            'type': 'inbox',
            'display': 'priority',
            'display_order': 2,
            'icon': 'icon-inbox',
            'label_color': '06-blue',
            'name': _('Inbox'),
        },
        'Blank': {
            'type': 'blank',
            'flag_editable': True,
            'display': 'invisible',
            'name': _('Blank'),
        },
        'Drafts': {
            'type': 'drafts',
            'flag_editable': True,
            'display': 'priority',
            'display_order': 1,
            'icon': 'icon-compose',
            'label_color': '03-gray-dark',
            'name': _('Drafts'),
        },
        'Outbox': {
            'type': 'outbox',
            'display': 'priority',
            'display_order': 3,
            'icon': 'icon-outbox',
            'label_color': '06-blue',
            'name': _('Outbox'),
        },
        'Sent': {
            'type': 'sent',
            'display': 'priority',
            'display_order': 4,
            'icon': 'icon-sent',
            'label_color': '03-gray-dark',
            'name': _('Sent'),
        },
        'Spam': {
            'type': 'spam',
            'flag_hides': True,
            'display': 'priority',
            'display_order': 5,
            'icon': 'icon-spam',
            'label_color': '10-orange',
            'name': _('Spam'),
        },
        'MaybeSpam': {
            'display': 'invisible',
            'icon': 'icon-spam',
            'label_color': '10-orange',
            'name': _('MaybeSpam'),
        },
        'Ham': {
            'type': 'ham',
            'display': 'invisible',
            'name': _('Ham'),
        },
        'Trash': {
            'type': 'trash',
            'flag_hides': True,
            'display': 'priority',
            'display_order': 6,
            'icon': 'icon-trash',
            'label_color': '13-brown',
            'name': _('Trash'),
        },
        # These are magical tags that perform searches and show
        # messages in contextual views.
        'All Mail': {
            'type': 'tag',
            'icon': 'icon-logo',
            'label_color': '06-blue',
            'search_terms': 'all:mail',
            'name': _('All Mail'),
            'display_order': 1000,
        },
        'Photos': {
            'type': 'tag',
            'icon': 'icon-photos',
            'label_color': '08-green',
            'search_terms': 'att:jpg',
            'name': _('Photos'),
            'template': 'photos',
            'display_order': 1001,
        },
        'Files': {
            'type': 'tag',
            'icon': 'icon-document',
            'label_color': '06-blue',          
            'search_terms': 'has:attachment',
            'name': _('Files'),
            'template': 'files',
            'display_order': 1002,
        },
        'Links': {
            'type': 'tag',
            'icon': 'icon-links',
            'label_color': '12-red',
            'search_terms': 'http',
            'name': _('Links'),
            'display_order': 1003,
        },
        # These are internal tags, used for tracking user actions on
        # messages, as input for machine learning algorithms. These get
        # automatically added, and may be automatically removed as well
        # to keep the working sets reasonably small.
        'mp_rpl': {'type': 'replied', 'label': False, 'display': 'invisible'},
        'mp_fwd': {'type': 'fwded', 'label': False, 'display': 'invisible'},
        'mp_tag': {'type': 'tagged', 'label': False, 'display': 'invisible'},
        'mp_read': {'type': 'read', 'label': False, 'display': 'invisible'},
        'mp_ham': {'type': 'ham', 'label': False, 'display': 'invisible'},
    }

    def command(self):
        session = self.session

        if session.config.sys.lockdown:
            return self._error(_('In lockdown, doing nothing.'))

        # Perform any required migrations
        Migrate(session).run(before_setup=True, after_setup=False)

        # Create local mailboxes
        session.config.open_local_mailbox(session)

        # Create standard tags and filters
        created = []
        for t in self.TAGS:
            if not session.config.get_tag_id(t):
                AddTag(session, arg=[t]).run(save=False)
                created.append(t)
            session.config.get_tag(t).update(self.TAGS[t])
        for stype, statuses in (('sig', SignatureInfo.STATUSES),
                                ('enc', EncryptionInfo.STATUSES)):
            for status in statuses:
                tagname = 'mp_%s-%s' % (stype, status)
                if not session.config.get_tag_id(tagname):
                    AddTag(session, arg=[tagname]).run(save=False)
                    created.append(tagname)
                session.config.get_tag(tagname).update({
                    'type': 'attribute',
                    'display': 'invisible',
                    'label': False,
                })

        if 'New' in created:
            session.ui.notify(_('Created default tags'))

        # Import all the basic plugins
        for plugin in PLUGINS:
            if plugin not in session.config.sys.plugins:
                session.config.sys.plugins.append(plugin)
        try:
            # If spambayes is not installed, this will fail
            import mailpile.plugins.autotag_sb
            if 'autotag_sb' not in session.config.sys.plugins:
                session.config.sys.plugins.append('autotag_sb')
                session.ui.notify(_('Enabling spambayes autotagger'))
        except ImportError:
            session.ui.warning(_('Please install spambayes '
                                 'for super awesome spam filtering'))
        session.config.save()
        session.config.load(session)

        vcard_importers = session.config.prefs.vcard.importers
        if not vcard_importers.gravatar:
            vcard_importers.gravatar.append({'active': True})
            session.ui.notify(_('Enabling gravatar image importer'))

        gpg_home = os.path.expanduser('~/.gnupg')
        if os.path.exists(gpg_home) and not vcard_importers.gpg:
            vcard_importers.gpg.append({'active': True,
                                        'gpg_home': gpg_home})
            session.ui.notify(_('Importing contacts from GPG keyring'))

        if ('autotag_sb' in session.config.sys.plugins and
                len(session.config.prefs.autotag) == 0):
            session.config.prefs.autotag.append({
                'match_tag': 'spam',
                'unsure_tag': 'maybespam',
                'tagger': 'spambayes',
                'trainer': 'spambayes'
            })
            session.config.prefs.autotag[0].exclude_tags[0] = 'ham'

        # Assumption: If you already have secret keys, you want to
        #             use the associated addresses for your e-mail.
        #             If you don't already have secret keys, you should have
        #             one made for you, if GnuPG is available.
        #             If GnuPG is not available, you should be warned.
        gnupg = GnuPG()
        accepted_keys = []
        if gnupg.is_available():
            keys = gnupg.list_secret_keys()
            for key, details in keys.iteritems():
                # Ignore revoked/expired keys.
                if ("revocation-date" in details and
                    details["revocation-date"] <=
                        date.today().strftime("%Y-%m-%d")):
                    continue

                accepted_keys.append(key)
                for uid in details["uids"]:
                    if "email" not in uid or uid["email"] == "":
                        continue

                    if uid["email"] in [x["email"]
                                        for x in session.config.profiles]:
                        # Don't set up the same e-mail address twice.
                        continue

                    # FIXME: Add route discovery mechanism.
                    profile = {
                        "email": uid["email"],
                        "name": uid["name"],
                    }
                    session.config.profiles.append(profile)
                if (not session.config.prefs.gpg_recipient
                   and details["capabilities"]["encrypt"]):
                    session.config.prefs.gpg_recipient = key
                    session.ui.notify(_('Encrypting config to %s') % key)
                if session.config.prefs.crypto_policy == 'none':
                    session.config.prefs.crypto_policy = 'openpgp-sign'

            if len(accepted_keys) == 0:
                # FIXME: Start background process generating a key once a user
                #        has supplied a name and e-mail address.
                pass

        else:
            session.ui.warning(_('Oh no, PGP/GPG support is unavailable!'))

        if (session.config.prefs.gpg_recipient
                and not (self._idx() and self._idx().INDEX)
                and not session.config.prefs.obfuscate_index):
            randcrap = sha512b64(open('/dev/urandom').read(1024),
                                 session.config.prefs.gpg_recipient,
                                 '%s' % time.time())
            session.config.prefs.obfuscate_index = randcrap
            session.config.prefs.index_encrypted = True
            session.ui.notify(_('Obfuscating search index and enabling '
                                'indexing of encrypted e-mail. '))

        # Perform any required migrations
        Migrate(session).run(before_setup=False, after_setup=True)

        session.config.save()
        return self._success(_('Performed initial Mailpile setup'))


_plugins.register_commands(Setup)
