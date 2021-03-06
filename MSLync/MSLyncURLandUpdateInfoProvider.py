#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2014 Allister Banks, wholesale lifted from code by Greg Neagle
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from __future__ import absolute_import

from distutils.version import LooseVersion
from operator import itemgetter

from autopkglib import Processor, ProcessorError, URLGetter

try:
    from plistlib import loads as readPlistFromString  # Python 3
except ImportError:
    from plistlib import readPlistFromString  # Python 2

__all__ = ["MSLyncURLandUpdateInfoProvider"]

# Some interesting URLs, for more see main MSOffice2011UpdateInfoProvider:

# Office 2011
# http://www.microsoft.com/mac/autoupdate/0409UCCP14.xml
CULTURE_CODE = "0409"
BASE_URL = "https://officecdn.microsoft.com/pr/C1297A47-86C4-4C1F-97FA-950631F94777/OfficeMac/%sUCCP14.xml"
MUNKI_UPDATE_NAME = "Lync_Installer"


class MSLyncURLandUpdateInfoProvider(URLGetter):
    """Provides a download URL for the most recent version of MS Lync."""
    input_variables = {
        "culture_code": {
            "required": False,
            "description": ("See "
                "http://msdn.microsoft.com/en-us/library/ee825488(v=cs.20).aspx"
                " for a table of CultureCodes Defaults to 0409, which "
                "corresponds to en-US (English - United States)"),
        },
        "base_url": {
            "required": False,
            "description": ("Default is %s. If this is given, culture_code "
                "is ignored." % (BASE_URL % CULTURE_CODE)),
        },
        "version": {
            "required": False,
            "description": "Update version number. Defaults to latest.",
        },
    }
    output_variables = {
        "url": {
            "description": "URL to the latest Lync installer.",
        },
        "pkg_name": {
            "description": "Name of the package within the disk image.",
        },
        "additional_pkginfo": {
            "description":
                "Some pkginfo fields extracted from the Microsoft metadata.",
        },
        "display_name": {
            "description":
                "The name of the package that includes the version.",
        },
    }
    description = __doc__

    def sanityCheckExpectedTriggers(self, item):
        """Raises an exeception if the Trigger Condition or
        Triggers for an update don't match what we expect.
        Protects us if these change in the future."""
        if not item.get("Trigger Condition") == ["and", "Lync"]:
            raise ProcessorError(
                "Unexpected Trigger Condition in item %s: %s"
                % (item["Title"], item["Trigger Condition"]))
        if not "Lync" in item.get("Triggers", {}):
            raise ProcessorError(
                "Missing expected MCP Trigger in item %s" % item["Title"])

    def getRequiresFromUpdateItem(self, item):
        """Attempts to determine what earlier updates are
        required by this update"""

        def compare_versions(a, b):
            """Internal comparison function for use with sorting"""
            return cmp(LooseVersion(a), LooseVersion(b))

        self.sanityCheckExpectedTriggers(item)
        munki_update_name = self.env.get("munki_update_name", MUNKI_UPDATE_NAME)
        mcp_versions = item.get(
            "Triggers", {}).get("Lync", {}).get("Versions", [])
        if not mcp_versions:
            return None
        # Versions array is already sorted in current 0409MSOf14.xml,
        # may be no need to sort; but we should just to be safe...
        mcp_versions = sorted(mcp_versions, key=LooseVersion)
        if mcp_versions[0] == "14.0.0":
            # works with original Office release, so no requires array
            return None
        return ["%s-%s" % (munki_update_name, mcp_versions[0])]

    def getInstallsItems(self, item):
        """Attempts to parse the Triggers to create an installs item"""
        self.sanityCheckExpectedTriggers(item)
        triggers = item.get("Triggers", {})
        paths = [triggers[key].get("File") for key in triggers.keys()]
        if "Contents/Info.plist" in paths:
            # use the apps info.plist as installs item
            installs_item = {
                "CFBundleShortVersionString": self.getVersion(item),
                "CFBundleVersion": self.getVersion(item),
                "path": ("/Applications/Lync/"
                         "Contents/Info.plist"),
                "type": "bundle",
                "version_comparison_key": "CFBundleShortVersionString"
            }
            return [installs_item]
        return None

    def getVersion(self, item):
        """Extracts the version of the update item."""
        # currently relies on the item having a title in the format
        # "Lync x.y.z Update"
        TITLE_START = "Lync "
        TITLE_END = " Update"
        title = item.get("Title", "")
        version_str = title.replace(TITLE_START, "").replace(TITLE_END, "")
        return version_str

    def valueToOSVersionString(self, value):
        """Converts a value to an OS X version number"""
        # Map string type for both Python 2 and Python 3.
        try:
            _ = basestring
        except NameError:
            basestring = str  # pylint: disable=W0622

        if isinstance(value, int):
            version_str = hex(value)[2:]
        elif isinstance(value, basestring):
            if value.startswith('0x'):
                version_str = value[2:]
        # OS versions are encoded as hex:
        # 4184 = 0x1058 = 10.5.8
        # not sure how 10.4.11 would be encoded;
        # guessing 0x104B ?
        major = 0
        minor = 0
        patch = 0
        try:
            if len(version_str) == 1:
                major = int(version_str[0])
            if len(version_str) > 1:
                major = int(version_str[0:2])
            if len(version_str) > 2:
                minor = int(version_str[2], 16)
            if len(version_str) > 3:
                patch = int(version_str[3], 16)
        except ValueError:
            raise ProcessorError("Unexpected value in version: %s" % value)
        return "%s.%s.%s" % (major, minor, patch)

    def get_lyncInstaller_info(self):
        """Gets info about a Lync installer from MS metadata."""
        if "base_url" in self.env:
            base_url = self.env["base_url"]
        else:
            culture_code = self.env.get("culture_code", CULTURE_CODE)
            base_url = BASE_URL % culture_code
        version_str = self.env.get("version")
        if not version_str:
            version_str = "latest"
        # Add the MAU User-Agent, since MAU feed server seems to explicitly block
        # a User-Agent of 'Python-urllib/2.7' - even a blank User-Agent string
        # passes.
        headers = {
            "User-Agent": "Microsoft%20AutoUpdate/3.0.2 CFNetwork/720.2.4 Darwin/14.1.0 (x86_64)",
        }
        try:
            data = self.download(base_url, headers=headers)
        except Exception as err:
            raise ProcessorError("Can't download %s: %s" % (base_url, err))

        metadata = readPlistFromString(data)
        if version_str == "latest":
            # Lync 'update' metadata is a list of dicts.
            # we need to sort by date.
            sorted_metadata = sorted(metadata, key=itemgetter('Date'))
            # choose the last item, which should be most recent.
            item = sorted_metadata[-1]
        else:
            # we've been told to find a specific version. Unfortunately, the
            # Lync updates metadata items don't have a version attibute.
            # The version is only in text in the update's Title. So we look for
            # that...
            # Titles are in the format "Lync x.y.z Update"
            padded_version_str = " " + version_str + " "
            matched_items = [item for item in metadata
                            if padded_version_str in item["Title"]]
            if len(matched_items) != 1:
                raise ProcessorError(
                    "Could not find version %s in update metadata. "
                    "Updates that are available: %s"
                    % (version_str, ", ".join(["'%s'" % item["Title"]
                                               for item in metadata])))
            item = matched_items[0]

        self.env["url"] = item["Location"]
        self.env["pkg_name"] = item["Payload"]
        self.output("Found URL %s" % self.env["url"])
        self.output("Got update: '%s'" % item["Title"])
        # now extract useful info from the rest of the metadata that could
        # be used in a pkginfo
        pkginfo = {}
        pkginfo["description"] = "<html>%s</html>" % item["Short Description"]
        pkginfo["display_name"] = item["Title"]
        max_os = self.valueToOSVersionString(item['Max OS'])
        min_os = self.valueToOSVersionString(item['Min OS'])
        if max_os != "0.0.0":
            pkginfo["maximum_os_version"] = max_os
        if min_os != "0.0.0":
            pkginfo["minimum_os_version"] = min_os
        installs_items = self.getInstallsItems(item)
        if installs_items:
            pkginfo["installs"] = installs_items
        requires = self.getRequiresFromUpdateItem(item)
        if requires:
            pkginfo["requires"] = requires
            self.output(
                "Update requires previous update version %s"
                % requires[0].split("-")[1])

        pkginfo['name'] = self.env.get("munki_update_name", MUNKI_UPDATE_NAME)
        self.env["additional_pkginfo"] = pkginfo
        self.env["display_name"] = pkginfo["display_name"]
        self.output("Additional pkginfo: %s" % self.env["additional_pkginfo"])

    def main(self):
        """Get information about an update"""
        self.get_lyncInstaller_info()


if __name__ == "__main__":
    processor = MSLyncURLandUpdateInfoProvider()
    processor.execute_shell()
