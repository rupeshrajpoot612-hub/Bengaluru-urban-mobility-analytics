# Shared schema constants for the MapReduce stage.
#
# The cleaning stage writes a header-less TSV (mapreduce_input.tsv) with a
# FIXED column order. Hadoop Streaming mappers do not reliably see a header
# line (each input split can start anywhere in the file on a real cluster),
# so real MapReduce jobs almost always rely on a fixed, documented schema
# instead of column names. These indices are that contract, and every
# mapper.py in pipeline/mapreduce/*/ imports this file.

MR_INPUT_COLUMNS = [
    "pickup_date",      # 0  YYYY-MM-DD
    "hour",             # 1  0-23
    "day_of_week",      # 2  0=Monday .. 6=Sunday
    "vehicle_type",     # 3  bike | auto | cab
    "pickup_zone",      # 4  hub name, e.g. "Koramangala"
    "dropoff_zone",     # 5  hub name
    "distance_km",      # 6  float
    "duration_min",     # 7  float
    "fare_inr",         # 8  float
    "is_peak_hour",     # 9  1 inside 08:30-11:30 / 17:30-21:30, else 0
    "delay_min",        # 10 float, minutes lost to congestion vs free flow
    "is_raining",       # 11 0/1
]

IDX_PICKUP_DATE = 0
IDX_HOUR = 1
IDX_DAY_OF_WEEK = 2
IDX_VEHICLE_TYPE = 3
IDX_PICKUP_ZONE = 4
IDX_DROPOFF_ZONE = 5
IDX_DISTANCE_KM = 6
IDX_DURATION_MIN = 7
IDX_FARE_INR = 8
IDX_IS_PEAK_HOUR = 9
IDX_DELAY_MIN = 10
IDX_IS_RAINING = 11
