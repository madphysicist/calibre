__license__   = 'GPL v3'
__copyright__ = '2008, Kovid Goyal <kovid at kovidgoyal.net>'

import re, binascii, cPickle
from future_builtins import map

from PyQt4.Qt import (QThread, pyqtSignal, Qt, QUrl, QDialog, QGridLayout,
        QLabel, QCheckBox, QDialogButtonBox, QIcon, QPixmap)
import mechanize

from calibre.constants import (__appname__, __version__, iswindows, isosx,
        isportable, is64bit, numeric_version)
from calibre import browser, prints, as_unicode
from calibre.utils.config import prefs
from calibre.gui2 import config, dynamic, open_url
from calibre.gui2.dialogs.plugin_updater import get_plugin_updates_available

URL = 'http://status.calibre-ebook.com/latest'
# URL = 'http://localhost:8000/latest'
NO_CALIBRE_UPDATE = (0, 0, 0)

def get_download_url():
    which = ('portable' if isportable else 'windows' if iswindows
            else 'osx' if isosx else 'linux')
    if which == 'windows' and is64bit:
        which += '64'
    return 'http://calibre-ebook.com/download_' + which

def get_newest_version():
    br = browser()
    req = mechanize.Request(URL)
    req.add_header('CALIBRE_VERSION', __version__)
    req.add_header('CALIBRE_OS',
            'win' if iswindows else 'osx' if isosx else 'oth')
    req.add_header('CALIBRE_INSTALL_UUID', prefs['installation_uuid'])
    version = br.open(req).read().strip()
    try:
        version = version.decode('utf-8').strip()
    except UnicodeDecodeError:
        version = u''
    ans = NO_CALIBRE_UPDATE
    m = re.match(ur'(\d+)\.(\d+).(\d+)$', version)
    if m is not None:
        ans = tuple(map(int, (m.group(1), m.group(2), m.group(3))))
    return ans

class CheckForUpdates(QThread):

    update_found = pyqtSignal(object, object)
    INTERVAL = 24*60*60

    def __init__(self, parent):
        QThread.__init__(self, parent)

    def run(self):
        while True:
            calibre_update_version = NO_CALIBRE_UPDATE
            plugins_update_found = 0
            try:
                version = get_newest_version()
                if version[:2] > numeric_version[:2]:
                    calibre_update_version = version
            except Exception as e:
                prints('Failed to check for calibre update:', as_unicode(e))
            try:
                update_plugins = get_plugin_updates_available(raise_error=True)
                if update_plugins is not None:
                    plugins_update_found = len(update_plugins)
            except Exception as e:
                prints('Failed to check for plugin update:', as_unicode(e))
            if calibre_update_version != NO_CALIBRE_UPDATE or plugins_update_found > 0:
                self.update_found.emit(calibre_update_version, plugins_update_found)
            self.sleep(self.INTERVAL)

class UpdateNotification(QDialog):

    def __init__(self, calibre_version, plugin_updates, parent=None):
        QDialog.__init__(self, parent)
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.resize(400, 250)
        self.l = QGridLayout()
        self.setLayout(self.l)
        self.logo = QLabel()
        self.logo.setMaximumWidth(110)
        self.logo.setPixmap(QPixmap(I('lt.png')).scaled(100, 100,
            Qt.IgnoreAspectRatio, Qt.SmoothTransformation))
        ver = calibre_version
        if ver.endswith('.0'):
            ver = ver[:-2]
        self.label = QLabel(('<p>'+
            _('New version <b>%(ver)s</b> of %(app)s is available for download. '
            'See the <a href="http://calibre-ebook.com/whats-new'
            '">new features</a>.'))%dict(
                app=__appname__, ver=ver))
        self.label.setOpenExternalLinks(True)
        self.label.setWordWrap(True)
        self.setWindowTitle(_('Update available!'))
        self.setWindowIcon(QIcon(I('lt.png')))
        self.l.addWidget(self.logo, 0, 0)
        self.l.addWidget(self.label, 0, 1)
        self.cb = QCheckBox(
            _('Show this notification for future updates'), self)
        self.l.addWidget(self.cb, 1, 0, 1, -1)
        self.cb.setChecked(config.get('new_version_notification'))
        self.cb.stateChanged.connect(self.show_future)
        self.bb = QDialogButtonBox(self)
        b = self.bb.addButton(_('&Get update'), self.bb.AcceptRole)
        b.setDefault(True)
        b.setIcon(QIcon(I('arrow-down.png')))
        if plugin_updates > 0:
            b = self.bb.addButton(_('Update &plugins'), self.bb.ActionRole)
            b.setIcon(QIcon(I('plugins/plugin_updater.png')))
            b.clicked.connect(self.get_plugins, type=Qt.QueuedConnection)
        self.bb.addButton(self.bb.Cancel)
        self.l.addWidget(self.bb, 2, 0, 1, -1)
        self.bb.accepted.connect(self.accept)
        self.bb.rejected.connect(self.reject)
        dynamic.set('update to version %s'%calibre_version, False)

    def get_plugins(self):
        from calibre.gui2.dialogs.plugin_updater import (PluginUpdaterDialog,
            FILTER_UPDATE_AVAILABLE)
        d = PluginUpdaterDialog(self.parent(),
                initial_filter=FILTER_UPDATE_AVAILABLE)
        d.exec_()

    def show_future(self, *args):
        config.set('new_version_notification', bool(self.cb.isChecked()))

    def accept(self):
        open_url(QUrl(get_download_url()))

        QDialog.accept(self)

class UpdateMixin(object):

    def __init__(self, opts):
        self.last_newest_calibre_version = NO_CALIBRE_UPDATE
        if not opts.no_update_check:
            self.update_checker = CheckForUpdates(self)
            self.update_checker.update_found.connect(self.update_found,
                    type=Qt.QueuedConnection)
            self.update_checker.start()

    def recalc_update_label(self, number_of_plugin_updates):
        self.update_found(self.last_newest_calibre_version, number_of_plugin_updates)

    def update_found(self, calibre_version, number_of_plugin_updates, force=False, no_show_popup=False):
        self.last_newest_calibre_version = calibre_version
        has_calibre_update = calibre_version != NO_CALIBRE_UPDATE
        has_plugin_updates = number_of_plugin_updates > 0
        self.plugin_update_found(number_of_plugin_updates)
        version_url = binascii.hexlify(cPickle.dumps((calibre_version, number_of_plugin_updates), -1))
        calibre_version = u'.'.join(map(unicode, calibre_version))

        if not has_calibre_update and not has_plugin_updates:
            self.status_bar.update_label.setVisible(False)
            return
        if has_calibre_update:
            plt = u''
            if has_plugin_updates:
                plt = _(' (%d plugin updates)')%number_of_plugin_updates
            msg = (u'<span style="color:green; font-weight: bold">%s: '
                    u'<a href="update:%s">%s%s</a></span>') % (
                        _('Update found'), version_url, calibre_version, plt)
        else:
            msg = (u'<a href="update:%s">%d %s</a>')%(version_url, number_of_plugin_updates,
                    _('updated plugins'))
        self.status_bar.update_label.setText(msg)
        self.status_bar.update_label.setVisible(True)

        if has_calibre_update:
            if (force or (config.get('new_version_notification') and
                    dynamic.get('update to version %s'%calibre_version, True))):
                if not no_show_popup:
                    self._update_notification__ = UpdateNotification(calibre_version,
                            number_of_plugin_updates, parent=self)
                    self._update_notification__.show()
        elif has_plugin_updates:
            if force:
                from calibre.gui2.dialogs.plugin_updater import (PluginUpdaterDialog,
                    FILTER_UPDATE_AVAILABLE)
                d = PluginUpdaterDialog(self,
                        initial_filter=FILTER_UPDATE_AVAILABLE)
                d.exec_()
                if d.do_restart:
                    self.quit(restart=True)

    def plugin_update_found(self, number_of_updates):
        # Change the plugin icon to indicate there are updates available
        plugin = self.iactions.get('Plugin Updater', None)
        if not plugin:
            return
        if number_of_updates:
            plugin.qaction.setText(_('Plugin Updates')+'*')
            plugin.qaction.setIcon(QIcon(I('plugins/plugin_updater_updates.png')))
            plugin.qaction.setToolTip(
                _('There are %d plugin updates available')%number_of_updates)
        else:
            plugin.qaction.setText(_('Plugin Updates'))
            plugin.qaction.setIcon(QIcon(I('plugins/plugin_updater.png')))
            plugin.qaction.setToolTip(_('Install and configure user plugins'))

    def update_link_clicked(self, url):
        url = unicode(url)
        if url.startswith('update:'):
            calibre_version, number_of_plugin_updates = cPickle.loads(binascii.unhexlify(url[len('update:'):]))
            self.update_found(calibre_version, number_of_plugin_updates, force=True)

