"""Main Module for the Restaurant-Search"""
import random
from typing import List
from typing import Union

import sqlalchemy
from sqlalchemy.orm import Session

from db.crud.bewertung import create_bewertung
from db.crud.bewertung import delete_bewertung
from db.crud.bewertung import get_all_user_bewertungen
from db.crud.bewertung import get_bewertung_from_user_to_rest
from db.crud.bewertung import update_bewertung
from db.crud.restaurant import create_restaurant
from db.crud.restaurant import get_restaurant_by_id
from schemes.scheme_filter import FilterRest
from schemes.scheme_rest import Restaurant
from schemes.scheme_rest import RestaurantBase
from schemes.scheme_rest import RestBewertungCreate
from schemes.scheme_rest import RestBewertungReturn
from schemes.scheme_user import UserBase
from tools import gapi


def get_assessments_from_user(db_session: Session, user: UserBase) -> Union[List[RestBewertungReturn], None]:
    """Get Bewertungen from a User to all restaurants

    Args:
        db_session (Session): Session to the DB -> See `db: Session = Depends(get_db)`
        user_mail (str): Mail of the User

    Returns:
        Union[List[RestBewertungReturn], None]: Return a List of all User or None
    """
    db_rests = get_all_user_bewertungen(db_session, user)
    scheme_rests = [
        RestBewertungReturn(comment=db_rest.kommentar, rating=db_rest.rating, timestamp=db_rest.zeitstempel)
        for db_rest in db_rests
    ]
    return scheme_rests


def add_assessment(db_session: Session, assessment: RestBewertungCreate) -> RestBewertungReturn:
    """Add the given assessment to the Database.

    Args:
        db_session (Session): Session to the DB -> See `db: Session = Depends(get_db)`
        assessment (RestBewertungCreate): The assessment need to be unique

    Raises: `sqlalchemy.exc.InvalidRequestError` if the User or Restaurant does not exist or the assessment is duplicated

    Returns:
        [RestBewertungReturn]: The created Restaurant
    """
    try:
        created_assessment = create_bewertung(db_session, assessment)
        return RestBewertungReturn(
            comment=created_assessment.kommentar,
            rating=created_assessment.rating,
            timestamp=created_assessment.zeitstempel,
        )
    except sqlalchemy.exc.SQLAlchemyError as error:
        raise error


def update_assessment(
    db_session: Session, old_assessment: RestBewertungCreate, new_assessment: RestBewertungCreate
) -> RestBewertungReturn:
    """Update the comment and rating of a existing assessment

    Args:
        db_session (Session): Session to the DB -> See `db: Session = Depends(get_db)`
        old_assessment (RestBewertungCreate): The current assessment
        new_assessment (RestBewertungCreate): The new assessment with the updated values

    Returns:
        RestBewertungReturn: Restaurant the the new values
    """
    updated_assessment = update_bewertung(db_session, old_assessment, new_assessment)
    return RestBewertungReturn(
        comment=updated_assessment.kommentar, rating=updated_assessment.rating, timestamp=updated_assessment.zeitstempel
    )


def delete_assessment(db_session: Session, user: UserBase, rest: RestaurantBase) -> int:
    """Delete one assessment that are mapped between the user and rest

    Args:
        db_session (Session): Session to the DB -> See `db: Session = Depends(get_db)`
        user (UserBase): The owner of the assessment
        rest (RestaurantBase): The mapped Restaurant

    Returns:
        int: The number of affected Rows of the delete
    """
    return delete_bewertung(db_session, user, rest)


def search_for_restaurant(db_session: Session, user: UserBase, user_f: FilterRest) -> Restaurant:
    """Do a full search for a Restaurant. This does the google search, weights the result with the user rating
    and choose one of the restaurants according to the weights

    Args:
        db_session (Session): Session to the DB -> See `db: Session = Depends(get_db)`
        user_f (FilterRest): Filter that are needed for the search

    Returns:
        Restaurant: The one choosen Restaurant where the user have to go now!
    """
    google_rests: List[Restaurant] = gapi.search_restaurant(user_f)
    filterd_rests: List[Restaurant] = apply_filter(google_rests, user_f)
    user_rests: List[Restaurant] = fill_user_rating(db_session, filterd_rests, user)
    restaurant = select_restaurant(user_rests)
    if get_restaurant_by_id(db_session, restaurant.place_id):
        create_restaurant(db_session, restaurant)
        add_assessment(db_session, RestBewertungCreate(person=user, restaurant=restaurant))
    return restaurant


def fill_user_rating(db_session: Session, rests: List[Restaurant], user: UserBase) -> List[Restaurant]:
    """Search in the connected DB if one restaurant got already rated from the user
    and if so add the value to the restaurant

    Args:
        db_session (Session): Session to the DB -> See `db: Session = Depends(get_db)`
        google_res (List[Restaurant]): Restaurants for lookup

    Returns:
        List[Restaurant]: Return of the input List with the user rating if one got found
    """
    for rest in rests:
        assessment = get_bewertung_from_user_to_rest(db_session, user, rest)
        if assessment is not None:
            rest.own_rating = assessment.rating

    return rests


def apply_filter(rests: List[Restaurant], user_f: FilterRest) -> List[Restaurant]:
    """Apply all filter (current only Rating)

    Args:
        rests (List[Restaurant]): List of all Restarants to apply the filter
        filter (FilterRest): The Filter with all informations

    Returns:
        List[Restaurant]: The filtered List of the restaurants
    """
    return filter_rating(rests, user_f.rating)


def filter_rating(rests: List[Restaurant], rating: int) -> List[Restaurant]:
    """Remove all Restaurants from the list under the given rating

    Args:
        rests (List[Restaurant]): List of all Restarants to filter
        rating (int): All under this number got removed

    Returns:
        List[Restaurant]: Filtered List based ob the rating
    """
    for res in rests:
        if res.rating < rating:
            rests.remove(res)
    return rests


def select_restaurant(rests: List[Restaurant]) -> Restaurant:
    """Select one restaurant with specific weight. weight = user_rating * 4 + google_rating * 2.
    If None rating found it will be count as 0

    Args:
        user_res (List[Restaurant]): The Rating of the Restaurants are optional

    Returns:
        Restaurant: The random chooses restaurant
    """
    weights: List[int] = []
    for res in rests:
        if res.own_rating is None:
            res.own_rating = 0
        if res.rating is None:
            res.rating = 0
        weights.append(res.own_rating * 4 + res.rating * 2)

    return random.choices(rests, weights=weights, k=1)[0]
