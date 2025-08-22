# views package 

# Auth views
from .auth import (
    credential_list_view,
    credential_view,
    delete_credential,
    get_auto_fetch_setting,
    save_auto_fetch_setting,
    signup_view,
    logout_view,
    check_main_account,
    check_username,
    check_email,
    login_view,
)

# Main views
from .main import (
    main_view,
    save_monthly_adjustment,
)

# Report views
from .reports import (
    report_view,
    publisher_report_view,
    save_other_revenue,
)

# Sales views
from .sales import (
    sales_report_view,
    sales_api_view,
    handle_excel_upload,
    handle_inline_edit,
    handle_sales_delete,
    handle_sales_group,
    handle_get_groups,
    handle_sales_ungroup,
    handle_sales_ungroup_multiple,
    generate_sales_context,
    generate_group_code,
    _calculate_monthly_changes,
)

# Purchase views
from .purchase import (
    purchase_report_view,
    publisher_detail_data_api,
    download_publisher_detail_excel,
    member_search_api,
)

# Dashboard views
from .dashboard import (
    dashboard_view,
)

# Data Collection views
from .data_collection import (
    data_collection_view,
    get_platform_aliases_grouped,
    get_last_fetched_times,
)

# Management views
from .management import (
    settlement_department_list,
    settlement_department_create,
    settlement_department_edit,
    settlement_department_delete,
    sales_excel_download_view,
    purchase_group_detail_api,
    purchase_group_batch_update,
    purchase_group_delete_api,
    ad_units_management_view,
    adsense_ad_units_api,
    admanager_ad_units_api,
    ad_units_data_api,
    _handle_ad_units_api,
    exchange_rate_list,
    exchange_rate_create,
    exchange_rate_edit,
    exchange_rate_delete,
) 