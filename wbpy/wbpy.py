import os
import logging
import urllib2
import time
import md5
import tempfile
import re
import numbers
try: 
    import simplejson as json
except ImportError: 
    import json 

import pycountry # For iso code conversions

logger = logging.getLogger(__name__)

def _fetch(url):
    """ Temp file cache, keeps pages for a day. """
    one_day_old = 60*60*24
    cache_dir = os.path.join(tempfile.gettempdir(), 'wbpy')
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir)
        logger.debug("Created cache directory " + cache_dir)
    logger.debug("Fetching %s ...", url)
    cache_path = os.path.join(cache_dir, md5.new(url).hexdigest())
    if os.path.exists(cache_path):
        if int(time.time()) - os.path.getmtime(cache_path) < one_day_old:
            logger.debug("Retrieving web page from cache.")
            return open(cache_path).read()
    logger.debug("URL not found in cache. Getting web page...")
    web_page = urllib2.urlopen(url).read()
    fd, tempname = tempfile.mkstemp()
    fp = os.fdopen(fd, 'w')
    fp.write(web_page)
    fp.close()
    os.rename(tempname, cache_path)
    logger.debug("%s saved to cache." % url)
    return web_page

def _convert_to_alpha2(code):
    # Convert code if it ISO one, else return
    try:
        code = code.upper()
        if len(code) == 2:
            return pycountry.countries.get(alpha2=code).alpha2
        if len(code) == 3:
            return pycountry.countries.get(alpha3=code).alpha2
    except (KeyError, AttributeError):
        return code

def _convert_to_alpha3(code):
    try:
        code = code.upper()
        if len(code) == 2:
            return pycountry.countries.get(alpha2=code).alpha3
        if len(code) == 3:
            return pycountry.countries.get(alpha3=code).alpha3
    except (KeyError, AttributeError):
        return code

class Indicators(object):
    def __init__(self, cache=_fetch):
        """ A connection to the World Bank Indicators API.

        self.cache can point to your own fetch(url) function, which takes a url 
        and returns a web page as a string.
        """
        self.fetch = cache
        self.base_url = "http://api.worldbank.org/"

    # ========== PUBLIC METHODS =========

    def get_country_indicators(self, indicator_codes, country_codes=None, 
            **kwargs):
        """ Get indicator metrics for countries.

        :param indicator_codes:     Required list of metric codes.
        :param country_codes:       List of countries to get indicator data for. 
                                    If None, queries all countries.
        :param match:               See ``match_data``.
        :param kwargs:              Language, date, mrv, gapfill, frequency.
        
        :returns:   Two dicts. The first contains the data, with nested keys: 
                    `Indicator code > ISO 2-digit country code > Date > Value`. 
                    The second dict contains the names/values for the 
                    indicator and country codes.
        """
        # Generate urls and concatenate multiple calls into one list.
        response_data = []
        if country_codes:
            country_codes = [_convert_to_alpha3(code) for code in country_codes]
            country_string = ";".join(country_codes)
        else:
            country_string = "all"
        for indicator_string in indicator_codes:
            url = "countries/{0}/indicators/{1}?".format(country_string, 
                    indicator_string)
            url = self._generate_indicators_url(url, **kwargs)
            response_data += self._get_api_response_as_json(url)

        # Arrange JSON data to be more accessible.
        results = {}
        info = dict(indicators={}, countries={})
        for dataset in response_data:
            country_id = dataset['country']['id']
            indicator_id = dataset['indicator']['id']
            date = dataset['date']
            if indicator_id not in results:
                results[indicator_id] = {}
            if country_id not in results[indicator_id]:
                results[indicator_id][country_id] = {}
            if date not in results[indicator_id][country_id]:
                results[indicator_id][country_id][date] = dataset['value']

            if indicator_id not in info['indicators']:
                info['indicators'][indicator_id] = dict(
                        value=dataset['indicator']['value'])
            if country_id not in info['countries']:
                info['countries'][country_id] = dict(
                        value=dataset['country']['value'])
        return results, info

    def get_indicators(self, indicator_codes=None, match=None,
            common_only=False, **kwargs):
        """ Make call to retrieve indicator codes and information.

        :param indicator_codes: List of codes, eg. SP.POP.TOTL for population.
                                If None, queries all (~8000).
        :param common_only:     Many of the indicators do not have wide country 
                                coverage.  If True, filters out those 
                                indicators that do not appear on the 
                                main website (leaving ~1500).
        :param match:           See ``match_data``.
        :param kwargs:          Language, source, topic.
        
        :returns:   Dict of indicators, using ID codes as keys.
        """
        results = self._get_indicator_data(indicator_codes, rest_url="indicator",
                response_key="id", match=match, **kwargs)
        if common_only == True:
            page = self.fetch("http://data.worldbank.org/indicator/all")
            ind_codes = re.compile("(?<=http://data.worldbank.org/indicator/)"\
                                   "[A-Za-z0-9\.]+(?=\">)")
            common_matches = {}
            code_matches = set([code.lower() for code in ind_codes.findall(page)])
            # If value contains an indicator code, include the key in the
            # results.
            for k, v in results.items():
                v_string = "{}".format(v).lower()
                for code_match in code_matches:
                    if code_match in v_string:
                        common_matches[k] = v
                        break
            return common_matches
        else:
            return results

    def get_countries(self, country_codes=None, match=None, **kwargs):
        """ Get info on countries, eg. ISO codes,
        longitude/latitude, capital city, income level, etc.

        :param country_code:    List of 2 or 3 letter ISO codes. If None, 
                                queries all.
        :param match:           See ``match_data``.
        :param kwargs:          Language, incomeLevel, lendingType, region.

        :returns:   Dict of countries using 2-letter ISO codes as keys.
        """
        if country_codes:
            country_codes = [_covert_to_alpha3(code) for code in country_codes]
        return self._get_indicator_data(country_codes, rest_url="country",
                match=match, response_key="iso2Code", **kwargs)

    def get_income_levels(self, income_codes=None, match=None, **kwargs):
        """ Get income categories.

        :param income_codes:    List of 3-letter ID codes. If None, queries all 
                                (~10). 
        :param match:           See ``match_data``.
        :param kwargs:          Language

        :returns:   Dict of income levels using ID codes as keys.
        """
        return self._get_indicator_data(income_codes, rest_url="incomelevel", 
                response_key="id", match=match, **kwargs)

    def get_lending_types(self, lending_codes=None, match=None, **kwargs):
        """ Get lending type categories. 

        :param lending_codes:   List of lending codes. If None, queries all (4).
        :param match:           See ``match_data``.
        :param kwargs:          Language

        :returns:   Dict of lending types using ID codes as keys.
        """
        return self._get_indicator_data(lending_codes, rest_url="lendingtype",
                response_key="id", match=match, **kwargs)

    def get_regions(self, region_codes=None, match=None, **kwargs):
        """ Get wider region names and codes. 

        :param region_codes:    List of 3-letter codes. If None, queries all 
                                (~26).
        :param match:           See ``match_data``.
        :param kwargs:          Language
                        
        :returns:   Dict of regions, using ID codes as keys.
        """
        return self._get_indicator_data(region_codes, rest_url="region", 
                response_key="code", match=match, **kwargs)

    def get_topics(self, topic_codes=None, match=None, **kwargs):
        """ Get Indicators topics. All indicators are mapped 
        to a topic, eg. Health, Private Sector. You can use the topic id as a
        filtering arg to ``get_indicators``. 

        :param topic_codes: List of topic IDs. If None, queries all (~20).
        :param match:       See ``match_data``.
        :param kwargs:      Language

        :returns:   Dict of topics usings ID numbers as keys.
        """
        return self._get_indicator_data(topic_codes, rest_url="topic", 
                response_key="id", match=match, **kwargs)

    def get_sources(self, source_codes=None, match=None, **kwargs):
        """ Get source info for the Indicators data .You can use the source id
        as a filtering arg to ``get_indicators``. (At time of
        writing, the API only returns source names, not the descriptions and
        URLs visible in the official documentation). 

        :param source_codes:    List of source IDs. If None, queries all (~27).
        :param match:           See ``match_data``.
        :param kwargs:          Language

        :returns:   Dict of sources using ID numbers as keys.
        """
        return self._get_indicator_data(source_codes, rest_url="source", 
                response_key="id", match=match, **kwargs)

    def print_codes(self, results, match=None):
        """ Print formatted list of API IDs + values/names for the results of
        any of the ``get`` functions.  (For ``get_country_indicators``, only the
        'info' dict will print properly, the 'data' one will not).

        :param match:   See ``match_data``.
        """
        # There some juggling depending on dict layout, as prefer to keep it
        # to one print function.

        # If this is the 'info' dict from ``get_country_indicators``, process
        # both halves (countries + indicators) separately:
        if results.has_key('countries'):
            self.print_codes(results['countries'])
        if results.has_key('indicators'):
            self.print_codes(results['indicators'])

        if match:
            results = self.match_data(match, results)

        # Natural sort the result keys for nicer print order
        def try_int(text):
            return int(text) if text.isdigit() else text
        def natural_keys(text):
            return [try_int(k) for k in re.split("(\d+)", text)]

        for k in sorted(results.keys(), key=natural_keys):
            v = results[k]
            for value_key in ['value', 'name']: 
                try:
                    print "{:30} {}".format(k, v[value_key])
                except KeyError:
                    pass

    def match_data(self, ss, results):
        """ For a given dict (eg. of ``get`` results), filter out all 
        keys that do not contain the match string in the value.
        (``get`` results mostly include the key as one of the value
        fields, so the key is searched implicitly). 

        :param ss:      The match string. You can pass a `match` param to other 
                        functions as a shorthand for filtering the data through 
                        this method.
        :param results: A dict. 

        :returns:   The input dict, with the non-matching keys filtered out.
        """
        ss = ss.lower()
        search_matches = {}
        for k, v in results.items():
            if ss in  "{}".format(v).lower():
                search_matches[k] = v
        return search_matches

    # ========== PRIVATE METHODS ==========

    def _generate_indicators_url(self, rest_url, **kwargs):
        """ Adds API root and query string options to an otherwise complete 
        endpoint, eg. "incomeLevel?", or "lendingType?key=val".
        """
        kwargs = {k.lower(): v for k, v in kwargs.items()}
        assert not (kwargs.has_key('topic') and kwargs.has_key('source'))

        # Fix any API options that shouldn't be accessible via wbpy.
        fixed_options = {'format': 'json', 'per_page': '10000'}
        banned_options = ['page']
        kwargs.update(fixed_options) 
        for k in banned_options:
            if k in kwargs.keys():
                del(kwargs[k])

        # If no dates given, use most recent value
        if all(key not in kwargs.keys() for key in ['mrv', 'date']):
            kwargs['mrv'] = 1

        # Some options are part of the url structure.
        options = []
        if 'source' in kwargs.keys():
            rest_url = "".join(["source/", str(kwargs["source"]), "/", 
                                rest_url])
            del(kwargs['source'])
        if 'topic' in kwargs.keys():
            rest_url = "".join(["topic/", str(kwargs["topic"]), "/", 
                                rest_url])
            del(kwargs['topic'])
        # Prepend language last, as it should be at front of url.
        if 'language' in kwargs.keys(): 
            rest_url = "{}/".format(kwargs['language']) + rest_url
            del(kwargs['language'])

        # Other options can be passed to the query string,
        # with numbers / lists converted to the right format for the url.
        for k, v in kwargs.items():
            if isinstance(v, numbers.Number):
                v = str(v)
            if not isinstance(v, basestring): 
                v = ";".join([str(x) for x in v]) 
            options.append("{0}={1}".format(k, v))

        query_string = '&'.join(options)
        new_url = "".join([self.base_url, rest_url, query_string])
        return new_url

    def _get_api_response_as_json(self, url):
        """ Returns JSON content from Indicators URL. Concatenates the returned
        list if request requires multiple-page responses.
        """
        web_page = self.fetch(url)
        json_data = json.loads(web_page)
        header = json_data[0]
        content = json_data[1]
        current_page = header['page']
        if current_page < header['pages']:
            next_page = url + "&page={0}".format(current_page + 1)
            content += self._get_api_response_as_json(next_page)
        return content

    def _get_indicator_data(self, api_ids, rest_url, response_key, match=None, **kwargs):
        """ 
        :param api_ids:         API codes for the indicator, eg. if calling a 
                                topic might be [1, 2, 5].
        :param rest_url:        The access point, eg. 'indicators', 
                                'lendingType'.
        :param response_key:    The key in the JSON response that will be 
                                used as the top-level keys in the returned dict.

        :returns:       Dict with keys that are the given response_key for the
                        API response.
        """
        if api_ids:
            rest_string = ";".join([str(x) for x in api_ids])
            url = "{0}/{1}?".format(rest_url, rest_string)
        else:
            url = "{0}?".format(rest_url)
        url = self._generate_indicators_url(url, **kwargs)
        world_bank_response = self._get_api_response_as_json(url)
        tidier_data = {}
        for data in world_bank_response:
            tidier_data[data[response_key]] = data
        if match:
            tidier_data = self.match_data(match, tidier_data)
        return tidier_data

class Climate(object):
    def __init__(self, cache=_fetch):
        self.fetch = cache
        self.base_url = "http://climatedataapi.worldbank.org/climateweb/rest/"

    def get_precip_instrumental(self, locations, interval="year"):
        return self._get_instrumental(var="pr", locations=locations,
                interval=interval)

    def get_temp_instrumental(self, locations, interval="year"):
        return self._get_instrumental(var="tas", locations=locations,
                interval=interval)

    def get_precip_modelled(self, data_type, locations, gcm=None,
        sres=None, ensemble_percentile=None):
        return self._get_modelled(var="pr", data_type=data_type,
                locations=locations, gcm=gcm, sres=sres,
                ensemble_percentile=None)

    def get_temp_modelled(self, data_type, locations, gcm=None,
        sres=None, ensemble_percentile=None):
        return self._get_modelled(var="tas", data_type=data_type,
                locations=locations, gcm=gcm, sres=sres,
                ensemble_percentile=None)

    def get_derived_stat(self, data_type, stat, locations, sres=None, 
            ensemble_percentile=None):
        return self._get_modelled(var=stat, data_type=data_type,
                locations=locations, sres=sres, 
                ensemble_percentile=ensemble_percentile, gcm='ensemble')

    def _get_instrumental(self, var, locations, interval="year"):
        # URL structures are different for countries and basins.
        urls = []
        for loc in locations:
            try:
                int(loc)
                basins_url = "v1/basin/cru/{0}/{1}/{2}".format(var, interval,
                                str(loc))
                full_url = "".join([self.base_url, basins_url, ".json"])
                urls.append((loc, full_url))
            except ValueError:
                loc = _convert_to_alpha3(loc)
                countries_url = "v1/country/cru/{0}/{1}/{2}".format(var, interval,
                                loc)
                full_url = "".join([self.base_url, countries_url, ".json"])
                urls.append((loc, full_url))

        results = {}
        for loc, url in urls:
            loc = _convert_to_alpha2(loc)
            response = json.loads(self.fetch(url))
            results[loc] = {}
            for data in response:
                # The response has different keys depending on the interval
                if interval == 'month':
                    # + 1 to month as it uses keys 0-11, unless I missing some
                    # domain-related reason I think 1-12 more sensible.
                    results[loc][data['month'] + 1] = data['data']
                else:
                    results[loc][data['year']] = data['data']
        return results

    def _get_modelled(self, var, data_type, locations, gcm=None,
        sres=None, ensemble_percentile=None):
        """ Single point of interaction, returns either an 
        ensemble or gcm call, as they have different url and response
        structures.
        """
        # You can input 'aavg', 'aanom', to go w/ the proper 'mavg', 'manom'.
        # The actual API code is 'annualavg', etc.
        if data_type.startswith('a'):
            data_type = data_type.replace('a', 'annual', 1) 
        try:
            gcm = gcm.lower()
        except AttributeError:
            pass

        locations = [_convert_to_alpha3(code) for code in locations]

        if gcm == 'ensemble':
            return self._get_modelled_ensemble(var=var, data_type=data_type,
                    locations=locations, sres=sres,
                    ensemble_percentile=ensemble_percentile)
        else:
            return self._get_modelled_gcm(var=var, data_type=data_type,
                    locations=locations, sres=sres,
                    gcm=gcm)

    def _get_modelled_gcm(self, var, data_type, locations, gcm=None,
        sres=None):
        """
        :gcm:       list, or 'ensemble'
        :sres:      str
        :returns:   Dict with one of the following layouts:
                        GCM id > location id > year or (year, sres) > value.
                        GCM id > location id > year or (year, sres) > month >
                            value.
        """
        valid_dates = ( # API allows fixed 19-yr date ranges
                1920, 1940, 1960, 1980,
                2020, 2040, 2060, 2080,
                )
        date_range = 19

        # Construct the requested urls
        urls = []
        for start_date in valid_dates:
            end_date = start_date + date_range
            for loc in locations:
                try:
                    int(loc) # basin ids are ints
                    loc_type = 'basin'
                except ValueError:
                    loc_type = 'country'
                rest_url = "v1/{0}/{1}/{2}/{3}/{4}/{5}".format(
                        loc_type, data_type,
                        var, start_date, end_date, loc)
                full_url = "".join([self.base_url, rest_url, ".json"])
                urls.append((loc, full_url))

        # Get responses and tidy results
        results = {}
        info = {}
        for loc, url in urls:
            loc = _convert_to_alpha2(loc)
            response = json.loads(self.fetch(url))
            for data in response:
                # L1 - GCM
                if data.has_key('gcm'):
                    gcm_key = data['gcm']
                if gcm_key not in results:
                    results[gcm_key] = {}

                # L2 - Location
                if loc not in results[gcm_key]:
                    results[gcm_key][loc] = {}

                # L3 - year / scenario
                time = data['fromYear']
                if data.has_key('scenario'):
                    time = (time, data['scenario'])
                if time not in results[gcm_key][loc]:
                    results[gcm_key][loc][time] = {}

                # L4 - values / months, depending on the result
                if data.has_key('monthVals'):
                    for i, val in enumerate(data['monthVals'], 1):
                        results[gcm_key][loc][time][i] = val
                elif data.has_key('annualVal'):
                    results[gcm_key][loc][time] = data['annualVal'][0]

        # Filter unwanted 
        if gcm:
            res_keys = results.keys()
            for k in res_keys:
                if k not in gcm:
                    del(results[k])
        if sres:
            for gcm_key in results:
                for loc in results[gcm_key]:
                    time_keys = results[gcm_key][loc].keys()
                    for k in time_keys:
                        if sres:
                            try: 
                                if k[1].lower() != sres.lower():
                                    del(results[gcm_key][loc][k])
                            except TypeError: 
                                # (Time only subscriptable if a tuple, ie.
                                # a future value with a sres)
                                pass

        return results

    def _get_modelled_ensemble(self, var, data_type, locations, sres=None,
            ensemble_percentile=None):

        if var not in ['pr', 'tas']:
            # Then assume it's a stat. Stat directly replaces the var API arg.
            # Only 2 or 3 date periods for future derived stats
            valid_dates = (1961, 2046, 2081) 
        else:
            valid_dates = ( 
                    1920, 1940, 1960, 1980,
                    2020, 2040, 2060, 2080,
                    )
        date_range = 19

        # Construct the requested urls
        urls = []
        for start_date in valid_dates:
            end_date = start_date + date_range
            # One exception - this range can be used for manom and aanom stats:
            if start_date == 1961:
                end_date = 2000 
            for loc in locations:
                try:
                    int(loc) # basin ids are ints
                    loc_type = 'basin'
                except ValueError:
                    loc_type = 'country'
                rest_url = "v1/{0}/{1}/ensemble/{2}/{3}/{4}/{5}".format(
                        loc_type, data_type, var, start_date, end_date, loc)
                full_url = "".join([self.base_url, rest_url, ".json"])
                urls.append((loc, full_url))

        # Get responses and tidy results
        results = {}
        info = {}
        for loc, url in urls:
            loc = _convert_to_alpha2(loc)
            response = json.loads(self.fetch(url))
            for data in response:
                # L1 - percentile
                gcm_key = ('ensemble', data['percentile'])
                if gcm_key not in results:
                    results[gcm_key] = {}
                # L2 - Location
                if loc not in results[gcm_key]:
                    results[gcm_key][loc] = {}
                # L3 - year / scenario
                time = data['fromYear']
                if data.has_key('scenario'):
                    time = (time, data['scenario'])
                if time not in results[gcm_key][loc]:
                    results[gcm_key][loc][time] = {}
                # L4 - values / months, depending on the result
                if data.has_key('monthVals'):
                    for i, val in enumerate(data['monthVals'], 1):
                        results[gcm_key][loc][time][i] = val
                elif data.has_key('annualVal'):
                    results[gcm_key][loc][time] = data['annualVal'][0]

        # If sres or ensemble_percentile values given, filter out unwanted
        # results. Best to get data in small no. of calls and to take out
        # unwanted, than to make a call for every percentile/GCM/SRES
        # variation.
        if ensemble_percentile:
            res_keys = results.keys()
            for k in res_keys:
                if str(k[0]) not in [str(x) for x in ensemble_percentiles]:
                    del(results[k])
        if sres:
            for gcm_key in results:
                for loc in results[gcm_key]:
                    time_keys = results[gcm_key][loc].keys()
                    for k in time_keys:
                        if sres:
                            try: 
                                if k[1].lower() != sres.lower():
                                    del(results[gcm_key][loc][k])
                            except TypeError: 
                                # (Time only subscriptable if a tuple, ie.
                                # a future value with a sres)
                                pass
        return results

