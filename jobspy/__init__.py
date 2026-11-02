from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Tuple

import pandas as pd

from jobspy.ashby import Ashby
from jobspy.bayt import BaytScraper
from jobspy.bestjobs import BestJobs
from jobspy.devjobro import DevJobRo
from jobspy.gem import Gem
from jobspy.workday import Workday
from jobspy.djinni import Djinni
from jobspy.ejobs import EJobs
from jobspy.bdjobs import BDJobs
from jobspy.glassdoor import Glassdoor
from jobspy.google import Google
from jobspy.greenhouse import Greenhouse
from jobspy.hackernews import HackerNews
from jobspy.himalayas import Himalayas
from jobspy.indeed import Indeed
from jobspy.joburiit import JoburiIT
from jobspy.larajobs import LaraJobs
from jobspy.lever import Lever
from jobspy.linkedin import LinkedIn
from jobspy.naukri import Naukri
from jobspy.nofluffjobs import NoFluffJobs
from jobspy.personio import Personio
from jobspy.phpjobsro import PhpJobsRo
from jobspy.hipo import Hipo
from jobspy.peviitor import Peviitor
from jobspy.recruitee import Recruitee
from jobspy.rippling import Rippling
from jobspy.remoterocketship import RemoteRocketship
from jobspy.smartrecruiters import SmartRecruiters
from jobspy.symfonyjobs import SymfonyJobs
from jobspy.teamtailor import Teamtailor
from jobspy.welcometothejungle import WelcomeToTheJungle
from jobspy.workable import Workable
from jobspy.model import JobType, Location, JobResponse, Country
from jobspy.model import SalarySource, ScraperInput, Site
from jobspy.util import (
    set_logger_level,
    extract_salary,
    create_logger,
    get_enum_from_value,
    map_str_to_site,
    convert_to_annual,
    desired_order,
)
from jobspy.ziprecruiter import ZipRecruiter


# Update the SCRAPER_MAPPING dictionary in the scrape_jobs function

def scrape_jobs(
    site_name: str | list[str] | Site | list[Site] | None = None,
    search_term: str | None = None,
    google_search_term: str | None = None,
    location: str | None = None,
    distance: int | None = 50,
    is_remote: bool = False,
    job_type: str | None = None,
    easy_apply: bool | None = None,
    results_wanted: int = 15,
    country_indeed: str = "usa",
    proxies: list[str] | str | None = None,
    ca_cert: str | None = None,
    description_format: str = "markdown",
    linkedin_fetch_description: bool | None = False,
    linkedin_company_ids: list[int] | None = None,
    offset: int | None = 0,
    hours_old: int = None,
    enforce_annual_salary: bool = False,
    verbose: int = 0,
    user_agent: str = None,
    company_boards: dict[str, list[str]] | None = None,
    **kwargs,
) -> pd.DataFrame:
    """
    Scrapes job data from job boards concurrently
    :return: Pandas DataFrame containing job data
    """
    SCRAPER_MAPPING = {
        Site.LINKEDIN: LinkedIn,
        Site.INDEED: Indeed,
        Site.ZIP_RECRUITER: ZipRecruiter,
        Site.GLASSDOOR: Glassdoor,
        Site.GOOGLE: Google,
        Site.BAYT: BaytScraper,
        Site.NAUKRI: Naukri,
        Site.BDJOBS: BDJobs,  # Add BDJobs to the scraper mapping
        Site.GREENHOUSE: Greenhouse,
        Site.ASHBY: Ashby,
        Site.LEVER: Lever,
        Site.HIMALAYAS: Himalayas,
        Site.WORKABLE: Workable,
        Site.LARAJOBS: LaraJobs,
        Site.SYMFONY_JOBS: SymfonyJobs,
        Site.WELCOME_TO_THE_JUNGLE: WelcomeToTheJungle,
        Site.PERSONIO: Personio,
        Site.RECRUITEE: Recruitee,
        Site.RIPPLING: Rippling,
        Site.JOBURIIT: JoburiIT,
        Site.PEVIITOR: Peviitor,
        Site.BESTJOBS: BestJobs,
        Site.EJOBS: EJobs,
        Site.NOFLUFFJOBS: NoFluffJobs,
        Site.DJINNI: Djinni,
        Site.REMOTE_ROCKETSHIP: RemoteRocketship,
        Site.HACKER_NEWS: HackerNews,
        Site.SMARTRECRUITERS: SmartRecruiters,
        Site.TEAMTAILOR: Teamtailor,
        Site.DEVJOB_RO: DevJobRo,
        Site.PHPJOBS_RO: PhpJobsRo,
        Site.HIPO: Hipo,
        Site.GEM: Gem,
        Site.WORKDAY: Workday,
    }
    set_logger_level(verbose)
    job_type = get_enum_from_value(job_type) if job_type else None

    def get_site_type():
        site_types = list(Site)
        if isinstance(site_name, str):
            site_types = [map_str_to_site(site_name)]
        elif isinstance(site_name, Site):
            site_types = [site_name]
        elif isinstance(site_name, list):
            site_types = [
                map_str_to_site(site) if isinstance(site, str) else site
                for site in site_name
            ]
        return site_types

    country_enum = Country.from_string(country_indeed)

    scraper_input = ScraperInput(
        site_type=get_site_type(),
        country=country_enum,
        search_term=search_term,
        google_search_term=google_search_term,
        location=location,
        distance=distance,
        is_remote=is_remote,
        job_type=job_type,
        easy_apply=easy_apply,
        description_format=description_format,
        linkedin_fetch_description=linkedin_fetch_description,
        results_wanted=results_wanted,
        linkedin_company_ids=linkedin_company_ids,
        offset=offset,
        hours_old=hours_old,
        company_boards=company_boards,
    )

    def scrape_site(site: Site) -> Tuple[str, JobResponse]:
        scraper_class = SCRAPER_MAPPING[site]
        scraper = scraper_class(proxies=proxies, ca_cert=ca_cert, user_agent=user_agent)
        scraped_data: JobResponse = scraper.scrape(scraper_input)
        cap_name = site.value.capitalize()
        site_name = "ZipRecruiter" if cap_name == "Zip_recruiter" else cap_name
        site_name = "LinkedIn" if cap_name == "Linkedin" else cap_name
        create_logger(site_name).info(f"finished scraping")
        return site.value, scraped_data

    site_to_jobs_dict = {}

    def worker(site):
        site_val, scraped_info = scrape_site(site)
        return site_val, scraped_info

    with ThreadPoolExecutor() as executor:
        future_to_site = {
            executor.submit(worker, site): site for site in scraper_input.site_type
        }

        for future in as_completed(future_to_site):
            site_value, scraped_data = future.result()
            site_to_jobs_dict[site_value] = scraped_data

    jobs_dfs: list[pd.DataFrame] = []

    for site, job_response in site_to_jobs_dict.items():
        for job in job_response.jobs:
            job_data = job.dict()
            job_url = job_data["job_url"]
            job_data["site"] = site
            job_data["company"] = job_data["company_name"]
            job_data["job_type"] = (
                ", ".join(job_type.value[0] for job_type in job_data["job_type"])
                if job_data["job_type"]
                else None
            )
            job_data["emails"] = (
                ", ".join(job_data["emails"]) if job_data["emails"] else None
            )
            if job_data["location"]:
                job_data["location"] = Location(
                    **job_data["location"]
                ).display_location()

            # Handle compensation
            compensation_obj = job_data.get("compensation")
            if compensation_obj and isinstance(compensation_obj, dict):
                job_data["interval"] = (
                    compensation_obj.get("interval").value
                    if compensation_obj.get("interval")
                    else None
                )
                job_data["min_amount"] = compensation_obj.get("min_amount")
                job_data["max_amount"] = compensation_obj.get("max_amount")
                job_data["currency"] = compensation_obj.get("currency", "USD")
                job_data["salary_source"] = SalarySource.DIRECT_DATA.value
                if enforce_annual_salary and (
                    job_data["interval"]
                    and job_data["interval"] != "yearly"
                    and job_data["min_amount"]
                    and job_data["max_amount"]
                ):
                    convert_to_annual(job_data)
            else:
                if country_enum == Country.USA:
                    (
                        job_data["interval"],
                        job_data["min_amount"],
                        job_data["max_amount"],
                        job_data["currency"],
                    ) = extract_salary(
                        job_data["description"],
                        enforce_annual_salary=enforce_annual_salary,
                    )
                    job_data["salary_source"] = SalarySource.DESCRIPTION.value

            job_data["salary_source"] = (
                job_data["salary_source"]
                if "min_amount" in job_data and job_data["min_amount"]
                else None
            )

            #naukri-specific fields
            job_data["skills"] = (
                ", ".join(job_data["skills"]) if job_data["skills"] else None
            )
            job_data["experience_range"] = job_data.get("experience_range")
            job_data["company_rating"] = job_data.get("company_rating")
            job_data["company_reviews_count"] = job_data.get("company_reviews_count")
            job_data["vacancy_count"] = job_data.get("vacancy_count")
            job_data["work_from_home_type"] = job_data.get("work_from_home_type")
            job_data["location_restrictions"] = (
                ", ".join(job_data["location_restrictions"])
                if job_data.get("location_restrictions")
                else None
            )

            job_df = pd.DataFrame([job_data])
            jobs_dfs.append(job_df)

    if jobs_dfs:
        # Step 1: Filter out all-NA columns from each DataFrame before concatenation
        filtered_dfs = [df.dropna(axis=1, how="all") for df in jobs_dfs]

        # Step 2: Concatenate the filtered DataFrames
        jobs_df = pd.concat(filtered_dfs, ignore_index=True)

        # Step 3: Ensure all desired columns are present, adding missing ones as empty
        for column in desired_order:
            if column not in jobs_df.columns:
                jobs_df[column] = None  # Add missing columns as empty

        # Reorder the DataFrame according to the desired order
        jobs_df = jobs_df[desired_order]

        # Step 4: Sort the DataFrame as required
        return jobs_df.sort_values(
            by=["site", "date_posted"], ascending=[True, False]
        ).reset_index(drop=True)
    else:
        return pd.DataFrame()


# Add BDJobs to __all__
__all__ = [
    "BDJobs",
]