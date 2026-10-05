import logging
import base64
import requests
import re
from datetime import datetime, date

from odoo import http, fields
from odoo.http import request

from odoo.addons.g2p_registration_portal_base.controllers.main import G2PregistrationPortalBase

_logger = logging.getLogger(__name__)


class G2PSocialRegistryModel(G2PregistrationPortalBase):
    def _validate_tz_phone(self, phone, strict_length=False, required=False):
        if not phone:
            return "is required." if required else None
        # Normalize: strip +255 or 255 or leading 0
        local = str(phone).strip()
        if local.startswith('+255'):
            local = local[4:]
        elif local.startswith('255'):
            local = local[3:]
        elif local.startswith('0'):
            local = local[1:]
        
        if not local and required:
            return "is required."
        if strict_length:
            # Beneficiary: must start with 6 or 7 and be exactly 9 digits
            if not re.match(r'^[67][0-9]{8}$', local):
                return "must start with 6 or 7 after +255 and be 9 digits."
        # Nominee: must start with 6 or 7 (no length restriction)
        elif local and not re.match(r'^[67][0-9]*$', local):
            return "must start with 6 or 7 after +255."
        return None

    @http.route("/portal/registration/zan_id_lookup", type="json", auth="user", csrf=False)
    def zan_id_lookup(self, zan_id):
        if not zan_id:
            return {"status": "ERROR", "message": "Zan ID is required"}

        # 1. Check in database
        id_type = request.env["g2p.id.type"].sudo().search([("name", "=", "Zanzibar ID")], limit=1)
        if not id_type:
            return {"status": "ERROR", "message": "Zanzibar ID type not found in system"}

        reg_id = (
            request.env["g2p.reg.id"]
            .sudo()
            .search([("id_type", "=", id_type.id), ("value", "=", zan_id.strip())], limit=1)
        )

        if reg_id and reg_id.partner_id:
            return {
                "status": "ALREADY_EXISTS",
                "message": "Beneficiary with this Zan ID already exists in the system."
            }

        # 2. Call External API
        try:
            url = "https://mock-api.credissuer.com/validate-zan"
            payload = {"zan_id": zan_id}
            response = requests.post(url, json=payload, timeout=10)

            if response.status_code == 200:
                result = response.json()
                status = result.get("status")

                if status and status.lower() == "success":
                    api_data = result.get("data", {})
                    

                    street2 = api_data.get("ward_name", "")
                    
                    # Gender Lookup
                    gender_str = api_data.get("gender", "")
                    gender_val = ""
                    if gender_str:
                        # Try exact or case-insensitive match on code, value, or name
                        domain = ['|', ('code', '=ilike', gender_str), ('value', '=ilike', gender_str)]
                        found = request.env["gender.type"].sudo().search(domain, limit=1)
                        if found:
                            gender_val = found.value
                        else:
                            # Fallback standard assumptions
                            if gender_str.lower() in ['female', 'f', 'woman']:
                                gender_val = 'female'
                            elif gender_str.lower() in ['male', 'm', 'man']:
                                gender_val = 'male'
                            else:
                                gender_val = gender_str
                    
                    data = {
                        "status": "SUCCESS",
                        "firstname": api_data.get("first_name", ""),
                        "lastname": api_data.get("surname", ""),
                        "middle_name": api_data.get("middle_name", ""),
                        "dob": api_data.get("dob", ""),
                        "gender": gender_val,
                        "mobile": api_data.get("mobile_number", ""),
                        "street": api_data.get("address", ""),
                        "street2": street2,
                        "benf_post_code": api_data.get("po_box", ""),
                        # "region": api_data.get("region", ""), # API doesn't return region
                        # "district": api_data.get("district", ""), # API doesn't return district
                    }

                    # Age Validation
                    dob_str = data.get("dob")
                    if dob_str:
                        try:
                            # Try parsing YYYY-MM-DD
                            dob = datetime.strptime(dob_str, "%Y-%m-%d").date()
                        except ValueError:
                            try:
                                # Try parsing DD-MM-YYYY
                                dob = datetime.strptime(dob_str, "%d-%m-%Y").date()
                            except ValueError:
                                dob = None
                        
                        if dob:
                            today = date.today()
                            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
                            if age < 69:
                                return {
                                    "status": "NOT_ELIGIBLE", 
                                    "message": f"The citizen is not eligible for ZUPS scheme!. Age is  {age}, but must be 69+."
                                }

                    return data
                else:
                    return {"status": "NOT_FOUND", "message": "Zan ID not found in external registry"}
            else:
                return {"status": "ERROR", "message": f"ZAN ID does not exist in eGAZ system, Please try with a Valid ZAN ID!"}
        except Exception as e:
            return {"status": "ERROR", "message": str(e)}

    @http.route("/portal/registration/nominee_zan_id_lookup", type="json", auth="user", csrf=False)
    def nominee_zan_id_lookup(self, nominee_zanid):
        if not nominee_zanid:
            return {"status": "ERROR", "message": "Zan ID is required"}

        # 1. Check in database
        # id_type = request.env["g2p.id.type"].sudo().search([("name", "=", "Nominee Zanzibar ID")], limit=1)
        
        # if id_type:
        #     reg_id = (
        #         request.env["g2p.reg.id"]
        #         .sudo()
        #         .search([("id_type", "=", id_type.id), ("value", "=", nominee_zanid.strip())], limit=1)
        #     )

        #     if reg_id and reg_id.partner_id:
        #         p = reg_id.partner_id
        #         # Prepare data from existing partner
        #         data = {
        #             "status": "ALREADY_EXISTS_BUT_FILL",
        #             "message": "Nominee already exists in the system.",
        #             "nominee_first_name": p.nominee_first_name or "",
        #             "nominee_last_name": p.nominee_last_name or "",
        #             # Map Gender (System uses 'male'/'female', check standard)
        #             "nominee_gender": p.nominee_gender or "", 
        #             "nominee_mobile": p.nominee_mobile or "",
        #             # Address mapping - assuming simple mapping for now
        #             "nominee_house_street": p.nominee_house_street or "",
        #             "nominee_shehia": p.nominee_shehia or "",
        #              # Region/District need codes or IDs? The frontend expects values that match the select options (usually IDs or Codes).
        #              # In main.py individual_update, we see p.region.id is used.
        #              # But in the frontend JS, it sets values.
        #              # Let's send both or send what works. The prev mock API sent Codes probably?
        #              # Mock API returned "region": "MJ", "district": "mjini" (codes).
        #              # So we should send Codes if possible.
        #             "nominee_region": p.nominee_region or "",
        #             "nominee_district": p.nominee_district or "",
        #             "nominee_rel_benf": p.nominee_rel_benf or "",
        #         }
        #         return data

        # 2. Call Mock API
        try:
            response = requests.get("https://mocki.io/v1/4661e182-00d4-4f26-a450-e4e96a7cc075", timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "SUCCESS":
                    # Map Mock API fields to Nominee Fields
                    # Mock: firstname, lastname, gender, mobile, street, street2...
                    mapped_data = {
                        "status": "SUCCESS",
                        "message": "Found!",
                        "nominee_first_name": data.get("firstname", ""),
                        "nominee_last_name": data.get("lastname", ""),
                        "nominee_gender": data.get("gender", "").lower(),
                        "nominee_mobile": data.get("mobile", ""),
                        "nominee_house_street": data.get("street", ""),
                        "nominee_shehia": data.get("street2", ""),
                        "nominee_rel_benf": data.get("relationship", ""),
                        # Mock API might return 'region'/'district' keys.
                        "nominee_region": data.get("region", ""),
                        "nominee_district": data.get("district", ""),
                        "nominee_post_code": data.get("postcode", ""),
                    }
                    return mapped_data
                else:
                    return {"status": "NOT_FOUND", "message": "Nominee Zan ID not found in external registry"}
            else:
                return {"status": "ERROR", "message": f"External API error: {response.status_code}"}
        except Exception as e:
            return {"status": "ERROR", "message": str(e)}

    @http.route(
        ["/portal/registration/group/create/submit"],
        type="http",
        auth="user",
        website=True,
        csrf=False,
    )
    def group_create_submit(self, **kw):
        try:
            head_name = kw.get("name")
            beneficiary_id = None

            additional_data = {
                "name": head_name,
                "birthdate": kw.get("birthdate"),
                "gender": kw.get("gender"),
                "email": kw.get("email"),
                "address": kw.get("address"),
                # Social Status Information
                "num_preg_lact_women": int(kw.get("num_preg_lact_women", 0))
                if kw.get("num_preg_lact_women")
                else 0,
                "num_malnourished_children": int(kw.get("num_malnourished_children", 0))
                if kw.get("num_malnourished_children")
                else 0,
                "num_disabled": int(kw.get("num_disabled", 0)) if kw.get("num_disabled") else 0,
                "type_of_disability": kw.get("type_of_disability"),
                # Economic Status Information
                "caste_ethnic_group": kw.get("caste_ethnic_group"),
                "belong_to_protected_groups": kw.get("belong_to_protected_groups"),
                "other_vulnerable_status": kw.get("other_vulnerable_status"),
                "income_sources": kw.get("income_sources"),
                "annual_income": kw.get("annual_income", False),
                "owns_two_wheeler": kw.get("owns_two_wheeler"),
                "owns_three_wheeler": kw.get("owns_three_wheeler"),
                "owns_four_wheeler": kw.get("owns_four_wheeler"),
                "owns_cart": kw.get("owns_cart"),
                "land_ownership": kw.get("land_ownership"),
                "type_of_land_owned": kw.get("type_of_land_owned"),
                "land_size": float(kw.get("land_size", 0.0)) if kw.get("land_size") else 0.0,
                "owns_house": kw.get("owns_house"),
                "owns_livestock": kw.get("owns_livestock"),
            }

            if kw.get("group_id"):
                beneficiary = request.env["res.partner"].sudo().browse(int(kw.get("group_id")))
                beneficiary.write(additional_data)
                beneficiary_id = beneficiary.id
            else:
                if head_name:
                    user = request.env.user

                    data = {
                        "is_registrant": True,
                        "is_group": True,
                        "user_id": user.id,
                    }

                    data.update(additional_data)
                    beneficiary_obj = request.env["res.partner"].sudo().create(data)
                    beneficiary_id = beneficiary_obj.id

                    # Create a group head as member
                    head_name_parts = head_name.split(" ")
                    h_given_name = head_name_parts[0]
                    h_family_name = head_name_parts[-1]

                    if len(head_name_parts) > 2:
                        h_addl_name = " ".join(head_name_parts[1:-1])
                    else:
                        h_addl_name = ""

                    formatted_name = f"{h_family_name} , {h_given_name} {h_addl_name}"

                    head_individual = (
                        request.env["res.partner"]
                        .sudo()
                        .create(
                            {
                                "name": formatted_name,
                                "given_name": h_given_name,
                                "addl_name": h_addl_name,
                                "family_name": h_family_name,
                                "email": kw.get("email"),
                                "address": kw.get("address"),
                                "birthdate": kw.get("birthdate"),
                                "gender": kw.get("gender"),
                                "is_registrant": True,
                                "is_group": False,
                                "user_id": user.id,
                            }
                        )
                    )

                    # Create membership relationship between head and group
                    group_membership_vals = [
                        (0, 0, {"individual": head_individual.id, "group": beneficiary_id})
                    ]

                    # Update the group with this membership
                    beneficiary_obj.write({"group_membership_ids": group_membership_vals})

            beneficiary = request.env["res.partner"].sudo().browse(beneficiary_id)

            if not beneficiary:
                return request.render(
                    "g2p_registration_portal_base.error_template",
                    {"error_message": "Beneficiary not found."},
                )

            return request.redirect("/portal/registration/group")

        except Exception as e:
            return request.render(
                "g2p_registration_portal_base.error_template",
                {"error_message": "An error occurred. Please try again later."},
            )

    @http.route(
        ["/portal/registration/individual/create/"],
        type="http",
        auth="user",
        csrf=False,
    )
    def individual_registrar_create(self, **kw):
        self.check_roles("Agent")
        gender = request.env["gender.type"].sudo().search([])
        
        all_regions = request.env["g2p.region"].sudo().search([])
        unique_regions_map = {}
        for r in all_regions:
            if r.name not in unique_regions_map:
                unique_regions_map[r.name] = r
        regions = list(unique_regions_map.values())

        districts = request.env["g2p.district"].sudo().search([])
        shehias = request.env["g2p.shehia"].sudo().search([("active", "=", True)])
        id_types = request.env["g2p.id.type"].sudo().search([])
        return request.render(
            "g2p_registration_portal_base.individual_registrant_form_template",
            {"gender": gender, "regions": regions, "districts": districts, "shehias": shehias, "id_types": id_types},
        )

    @http.route(
        ["/portal/registration/individual/update/<int:_id>"],
        type="http",
        auth="user",
        csrf=False,
    )
    def indvidual_update(self, _id, **kw):
        self.check_roles("Agent")
        try:
            gender = request.env["gender.type"].sudo().search([])
            
            all_regions = request.env["g2p.region"].sudo().search([])
            unique_regions_map = {}
            for r in all_regions:
                if r.name not in unique_regions_map:
                    unique_regions_map[r.name] = r
            regions = list(unique_regions_map.values())

            districts = request.env["g2p.district"].sudo().search([])
            shehias = request.env["g2p.shehia"].sudo().search([("active", "=", True)])
            id_types = request.env["g2p.id.type"].sudo().search([])
            beneficiary = request.env["res.partner"].sudo().browse(_id)
            if not beneficiary:
                return request.render(
                    "g2p_registration_portal_base.error_template",
                    {"error_message": "Beneficiary not found."},
                )

            return request.render(
                "g2p_registration_portal_base.individual_update_form_template",
                {
                    "beneficiary": beneficiary,
                    "gender": gender,
                    "regions": regions,
                    "districts": districts,
                    "shehias": shehias,
                    "id_types": id_types,
                },
            )
        except Exception:
            return request.render(
                "g2p_registration_portal_base.error_template",
                {"error_message": "Invalid URL."},
            )

    @http.route(
        ["/portal/registration/individual/view/<int:_id>"],
        type="http",
        auth="user",
        csrf=False,
    )
    def individual_view_details(self, _id, **kw):
        """
        View Individual Details (Read-Only)
        """
        self.check_roles("Agent")

        try:
            gender = request.env["gender.type"].sudo().search([])
            
            # Fetch Regions
            regions = request.env["g2p.region"].sudo().search([])

            # Fetch Districts
            districts = request.env["g2p.district"].sudo().search([])
            
            # Fetch ID Types
            id_types = request.env["g2p.id.type"].sudo().search([])

            # Fetch Beneficiary
            beneficiary = request.env["res.partner"].sudo().browse(_id)

            if not beneficiary:
                return request.render(
                    "g2p_registration_portal_base.error_template",
                    {"error_message": "Beneficiary not found."},
                )

            return request.render(
                "g2p_social_registry_model.individual_view_details_readonly",
                {
                    "beneficiary": beneficiary,
                    "gender": gender,
                    "regions": regions,
                    "districts": districts,
                    "id_types": id_types,
                },
            )

        except Exception as e:
            _logger.exception("Error loading individual details view: %s", str(e))
            return request.render(
                "g2p_registration_portal_base.error_template",
                {"error_message": "An error occurred while loading the view: " + str(e)},
            )

        return reg_ids

    def _get_reg_ids_command(self, kw):
        reg_ids = []


        # Zanzibar ID
        if kw.get("benf_zan_id"):
            id_type = request.env["g2p.id.type"].sudo().search([("name", "=", "Zanzibar ID")], limit=1)
            if id_type:
                reg_ids.append((0, 0, {
                    "id_type": id_type.id,
                    "value": kw.get("benf_zan_id"),
                    "status": "valid",
                }))

        # Nominee Zanzibar ID
        if kw.get("nominee_zanid"):
            id_type = request.env["g2p.id.type"].sudo().search([("name", "=", "Nominee Zanzibar ID")], limit=1)
            if id_type:
                reg_ids.append((0, 0, {
                    "id_type": id_type.id,
                    "value": kw.get("nominee_zanid"),
                    "status": "valid",
                }))
        
        return reg_ids

    @http.route(
        ["/portal/registration/individual/create/submit"],
        type="http",
        auth="user",
        website=True,
        csrf=False,
    )
    def individual_create_submit(self, **kw):
        try:
            # Validate phone numbers before processing
            phone_error = self._validate_tz_phone(kw.get("mobile"), strict_length=True, required=True)
            if phone_error:
                return request.render(
                    "g2p_registration_portal_base.error_template",
                    {"error_message": f"Beneficiary Mobile: {phone_error}"},
                )
            nominee_phone_error = self._validate_tz_phone(kw.get("nominee_mobile"))
            if nominee_phone_error:
                return request.render(
                    "g2p_registration_portal_base.error_template",
                    {"error_message": f"Nominee Mobile: {nominee_phone_error}"},
                )

            user = request.env.user
            name = ""
            name_parts = [
                kw.get("given_name"),
                kw.get("middle_name"),
                kw.get("addl_name"),
                kw.get("family_name"),
            ]
            name = " ".join(p.strip() for p in name_parts if p and p.strip())
            if kw.get("birthdate") == "":
                birthdate = False
            else:
                birthdate = kw.get("birthdate")

            data = {
                "given_name": kw.get("given_name"),
                "middle_name": kw.get("middle_name"),
                "addl_name": kw.get("addl_name"),
                "family_name": kw.get("family_name"),
                "name": name.strip(),
                "birthdate": birthdate,
                "gender": kw.get("gender"),
                "email": kw.get("email"),
                "user_id": user.id,
                "is_registrant": True,
                "is_group": False,
                # Additional fields
                "address": ", ".join(filter(None, [kw.get("street"), kw.get("street2")])),
                "occupation": kw.get("occupation"),
                "income": float(kw.get("income", 0.0)) if kw.get("income") else 0.0,
                "education_level": kw.get("education_level"),
                "employment_status": kw.get("employment_status"),
                "marital_status": kw.get("marital_status"),
                # Nominee Info
                "nominee_first_name": kw.get("nominee_first_name"),
                "nominee_middle_name": kw.get("nominee_middle_name"),
                "nominee_last_name": kw.get("nominee_last_name"),
                "nominee_mobile": kw.get("nominee_mobile"),
                "nominee_gender": kw.get("nominee_gender"),
                # "nominee_zanid" removed (stored in reg_ids)
                "nominee_rel_benf": kw.get("nominee_rel_benf"),
                "nominee_house_street": kw.get("nominee_house_street"),
                "nominee_shehia": kw.get("nominee_shehia"),
                "nominee_region": kw.get("nominee_region"),
                "nominee_district": kw.get("nominee_district"),
                "nominee_post_code": kw.get("nominee_post_code"),
                # Pension Info
                "other_pension": kw.get("other_pension"),
                "scheme_name": kw.get("scheme_name"),
                # Payment Info
                "payment_mode": kw.get("payment_mode"),
                "bank_name": kw.get("bank_name"),
                "account_num": kw.get("account_num"),
                "account_name": kw.get("account_name"),
                "mobile_wallet": kw.get("mobile_wallet"),
                # New Fields
                "street": kw.get("street"),
                "street2": kw.get("street2"),
                "region": int(kw.get("region")) if kw.get("region") else False,
                "district": int(kw.get("district")) if kw.get("district") else False,
                "benf_post_code": kw.get("benf_post_code"),
                "benf_post_code": kw.get("benf_post_code"),
                # "benf_zan_id" removed (stored in reg_ids)
                "disability": kw.get("disability"),
                "type_of_disability": kw.get("type_of_disability"),
                "is_receiving_allowance": kw.get("is_receiving_allowance"),
                "has_health_insurance": kw.get("has_health_insurance"),

            }

            # Add reg_ids logic
            reg_ids = self._get_reg_ids_command(kw)
            if reg_ids:
                data["reg_ids"] = reg_ids

            if kw.get("nominee_image"):
                data["nominee_image"] = base64.b64encode(kw.get("nominee_image").read())
            if kw.get("zan_image"):
                data["zan_image"] = base64.b64encode(kw.get("zan_image").read())
            if kw.get("beneficiary_image"):
                data["image_1920"] = base64.b64encode(kw.get("beneficiary_image").read())

            partner = request.env["res.partner"].sudo().create(data)
            if kw.get("mobile"):
                request.env["g2p.phone.number"].sudo().create(
                    {
                        "partner_id": partner.id,
                        "phone_no": kw.get("mobile"),
                        "phone_owner": "beneficiary",
                        "country_id": request.env.ref("base.tz").id,
                    }
                )
                # Sync phone field for list view
                partner.sudo().write({"phone": kw.get("mobile")})

            return request.redirect("/portal/registration/individual")

        except Exception as e:
            _logger.exception("Error while submitting individual registration: %s", str(e))
            return request.render(
                "g2p_registration_portal_base.error_template",
                {"error_message": f"Error while submitting individual registration: {str(e)}"},
            )

    @http.route(
        "/portal/registration/individual/update/submit",
        type="http",
        auth="user",
        website=True,
        csrf=False,
    )
    def update_individual_submit(self, **kw):
        try:
            # Validate phone numbers
            phone_error = self._validate_tz_phone(kw.get("mobile"), strict_length=True, required=True)
            if phone_error:
                return request.render(
                    "g2p_registration_portal_base.error_template",
                    {"error_message": f"Beneficiary Mobile: {phone_error}"},
                )
            nominee_phone_error = self._validate_tz_phone(kw.get("nominee_mobile"))
            if nominee_phone_error:
                return request.render(
                    "g2p_registration_portal_base.error_template",
                    {"error_message": f"Nominee Mobile: {nominee_phone_error}"},
                )

            member = request.env["res.partner"].sudo().browse(int(kw.get("group_id")))
            if member:
                # Fields mapping from kw to vals
                field_map = {
                    "given_name": "given_name",
                    "middle_name": "middle_name",
                    "addl_name": "addl_name",
                    "family_name": "family_name",
                    "gender": "gender",
                    "email": "email",
                    "occupation": "occupation",
                    "education_level": "education_level",
                    "employment_status": "employment_status",
                    "marital_status": "marital_status",
                    "nominee_first_name": "nominee_first_name",
                    "nominee_middle_name": "nominee_middle_name",
                    "nominee_last_name": "nominee_last_name",
                    "nominee_mobile": "nominee_mobile",
                    "nominee_gender": "nominee_gender",
                    "nominee_rel_benf": "nominee_rel_benf",
                    "nominee_house_street": "nominee_house_street",
                    "nominee_shehia": "nominee_shehia",
                    "nominee_region": "nominee_region",
                    "nominee_district": "nominee_district",
                    "nominee_post_code": "nominee_post_code",
                    "other_pension": "other_pension",
                    "scheme_name": "scheme_name",
                    "payment_mode": "payment_mode",
                    "bank_name": "bank_name",
                    "account_num": "account_num",
                    "account_name": "account_name",
                    "mobile_wallet": "mobile_wallet",
                    "street": "street",
                    "street2": "street2",
                    "benf_post_code": "benf_post_code",
                    "disability": "disability",
                    "type_of_disability": "type_of_disability",
                    "is_receiving_allowance": "is_receiving_allowance",
                    "has_health_insurance": "has_health_insurance",
                }

                def normalize_space(text):
                    if not isinstance(text, str):
                        return text
                    return " ".join(text.split()).strip()

                vals = {}
                for kw_key, val_key in field_map.items():
                    if kw_key in kw:
                        new_val = kw.get(kw_key)
                        current_val = getattr(member, val_key)
                        
                        # Normalize comparisons: treat False, None, and empty string as equivalent for strings
                        norm_current = normalize_space(current_val) if isinstance(current_val, str) else (current_val or False)
                        norm_new = normalize_space(new_val) if isinstance(new_val, str) else (new_val or False)
                        
                        if norm_current != norm_new:
                            vals[val_key] = new_val

                # Special handling for birthdate
                if "birthdate" in kw:
                    new_birthdate = kw.get("birthdate") if kw.get("birthdate") != "" else False
                    current_birthdate = member.birthdate or False
                    if str(current_birthdate) != str(new_birthdate):
                        vals["birthdate"] = new_birthdate

                # Special handling for address (computed from street/street2)
                if "street" in kw or "street2" in kw:
                    street = kw.get("street") if "street" in kw else (member.street or "")
                    street2 = kw.get("street2") if "street2" in kw else (member.street2 or "")
                    new_address = ", ".join(filter(None, [street, street2]))
                    if normalize_space(member.address) != normalize_space(new_address):
                        vals["address"] = new_address

                # Special handling for numeric fields
                if "income" in kw:
                    try:
                        new_income = float(kw.get("income", 0.0))
                        if member.income != new_income:
                            vals["income"] = new_income
                    except (ValueError, TypeError):
                        pass

                # Special handling for relational fields (M2O)
                if "region" in kw:
                    new_region = int(kw.get("region")) if kw.get("region") else False
                    if (member.region.id if member.region else False) != new_region:
                        vals["region"] = new_region
                if "district" in kw:
                    new_district = int(kw.get("district")) if kw.get("district") else False
                    if (member.district.id if member.district else False) != new_district:
                        vals["district"] = new_district

                # Special handling for name construction and stripping whitespace
                if any(k in kw for k in ["family_name", "given_name", "middle_name", "addl_name"]):
                    f_name = kw.get("family_name") if "family_name" in kw else (member.family_name or "")
                    g_name = kw.get("given_name") if "given_name" in kw else (member.given_name or "")
                    m_name = kw.get("middle_name") if "middle_name" in kw else (member.middle_name or "")
                    a_name = kw.get("addl_name") if "addl_name" in kw else (member.addl_name or "")
                    
                    # Construct and normalize the new name: First Name, Middle Name, Additional Name, Surname
                    new_parts = []
                    if g_name: new_parts.append(g_name)
                    if m_name: new_parts.append(m_name)
                    if a_name: new_parts.append(a_name)
                    if f_name: new_parts.append(f_name)
                    new_name = " ".join(" ".join(new_parts).split()).strip()
                    
                    if normalize_space(member.name) != new_name:
                        vals["name"] = new_name


                # ID Handling Logic
                reg_ids_commands = []


                # Zanzibar ID
                if kw.get("benf_zan_id"):
                    id_type = request.env["g2p.id.type"].sudo().search([("name", "=", "Zanzibar ID")], limit=1)
                    if id_type:
                        existing_id = member.reg_ids.filtered(lambda r: r.id_type.id == id_type.id)
                        vals_id = {"value": kw.get("benf_zan_id"), "status": "valid"}
                        if existing_id:
                            reg_ids_commands.append((1, existing_id[0].id, vals_id))
                        else:
                            reg_ids_commands.append((0, 0, {"id_type": id_type.id, **vals_id}))

                # Nominee Zanzibar ID
                if kw.get("nominee_zanid"):
                    id_type = request.env["g2p.id.type"].sudo().search([("name", "=", "Nominee Zanzibar ID")], limit=1)
                    if id_type:
                        existing_id = member.reg_ids.filtered(lambda r: r.id_type.id == id_type.id)
                        vals_id = {"value": kw.get("nominee_zanid"), "status": "valid"}
                        if existing_id:
                            reg_ids_commands.append((1, existing_id[0].id, vals_id))
                        else:
                            reg_ids_commands.append((0, 0, {"id_type": id_type.id, **vals_id}))

                if reg_ids_commands:
                    vals["reg_ids"] = reg_ids_commands

                member.sudo().write(vals)

                if kw.get("mobile"):
                    phone_no = normalize_space(kw.get("mobile"))
                    
                    # 1. Disable all other active beneficiary phones for this partner
                    other_beneficiary_phones = request.env["g2p.phone.number"].sudo().search([
                        ("partner_id", "=", member.id),
                        ("phone_owner", "in", ["beneficiary", False]), # Cover legacy/default cases
                        ("phone_no", "!=", phone_no),
                        ("disabled", "=", False)
                    ])
                    for p in other_beneficiary_phones:
                        p.write({
                            "disabled": fields.Datetime.now(),
                            "disabled_by": request.env.user.id
                        })
                    
                    # 2. Ensure the provided mobile number is active and owned by beneficiary
                    phone_rec = (
                        request.env["g2p.phone.number"]
                        .sudo()
                        .search(
                            [
                                ("partner_id", "=", member.id),
                                ("phone_no", "=", phone_no),
                                ("phone_owner", "=", "beneficiary"),
                            ],
                            limit=1
                        )
                    )
                    if phone_rec:
                        if phone_rec.disabled:
                            phone_rec.write({"disabled": False, "disabled_by": False})
                    else:
                        request.env["g2p.phone.number"].sudo().create(
                            {
                                "partner_id": member.id,
                                "phone_no": phone_no,
                                "phone_owner": "beneficiary",
                                "country_id": request.env.ref("base.tz").id,
                            }
                        )
                        
                    if normalize_space(member.phone) != phone_no:
                        member.sudo().write({"phone": phone_no})
                if kw.get("nominee_image"):
                    member.sudo().write({"nominee_image": base64.b64encode(kw.get("nominee_image").read())})
                if kw.get("zan_image"):
                    member.sudo().write({"zan_image": base64.b64encode(kw.get("zan_image").read())})
                if kw.get("beneficiary_image"):
                    image_data = base64.b64encode(kw.get("beneficiary_image").read())
                    member.sudo().write({
                        "image_1920": image_data,
                        "beneficiary_image": image_data
                    })
            return request.redirect("/portal/registration/individual")

        except Exception as e:
            _logger.error("Error occurred: %s" % e)
            return request.render(
                "g2p_registration_portal_base.error_template",
                {"error_message": f"An error occurred: {str(e)}"},
            )
