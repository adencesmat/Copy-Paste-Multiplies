"""Castle Rock, CO real-estate lead pipeline.

Pulls Douglas County foreclosures and Castle Rock obituaries, cross-references
each against county parcel/assessor GIS data, dedupes against a local history,
and emits a daily report.
"""

__version__ = "1.0.0"
