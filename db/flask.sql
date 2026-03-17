
--
-- Table structure for table `stock_info`
--

DROP TABLE IF EXISTS `stock_info`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `stock_info` (
  `CODE` varchar(50) COLLATE utf8_unicode_ci DEFAULT NULL,
  `NAME` varchar(200) COLLATE utf8_unicode_ci DEFAULT NULL,
  `EXCHANGE` varchar(50) COLLATE utf8_unicode_ci DEFAULT NULL,
  `INDUSTRY` varchar(200) COLLATE utf8_unicode_ci DEFAULT NULL,
  `REGION` varchar(200) COLLATE utf8_unicode_ci DEFAULT NULL,
  `CONCEPT` varchar(200) COLLATE utf8_unicode_ci DEFAULT NULL,
  `STATUS` tinyint(4) DEFAULT NULL,
  `PROVINCE` varchar(50) COLLATE utf8_unicode_ci DEFAULT NULL,
  `CITY` varchar(50) COLLATE utf8_unicode_ci DEFAULT NULL,
  `INTRODUCTION` varchar(1000) COLLATE utf8_unicode_ci DEFAULT NULL,
  `MAIN_BUSINESS` varchar(2000) COLLATE utf8_unicode_ci DEFAULT NULL,
  `BUSINESS_SCOPE` varchar(2000) COLLATE utf8_unicode_ci DEFAULT NULL,
  `EMPLOYEES` int(11) DEFAULT NULL,
  `CREATE_TIME` datetime DEFAULT NULL,
  `UPDATE_TIME` datetime DEFAULT NULL
) ENGINE=MyISAM DEFAULT CHARSET=utf8 COLLATE=utf8_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `stock_report_data`
--

DROP TABLE IF EXISTS `stock_report_data`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `stock_report_data` (
  `id` int(11) DEFAULT NULL,
  `code` varchar(50) COLLATE utf8_unicode_ci DEFAULT NULL,
  `report_type` varchar(50) COLLATE utf8_unicode_ci DEFAULT NULL,
  `period` varchar(50) COLLATE utf8_unicode_ci DEFAULT NULL,
  `account` varchar(500) COLLATE utf8_unicode_ci DEFAULT NULL,
  `amount` double DEFAULT NULL,
  `create_time` datetime DEFAULT NULL,
  `update_time` datetime DEFAULT NULL
) ENGINE=MyISAM DEFAULT CHARSET=utf8 COLLATE=utf8_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `user`
--

DROP TABLE IF EXISTS `user`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `user` (
  `uid` int(11) NOT NULL AUTO_INCREMENT,
  `username` varchar(50) COLLATE utf8_unicode_ci DEFAULT NULL,
  `password` varchar(50) COLLATE utf8_unicode_ci DEFAULT NULL,
  `email` varchar(50) COLLATE utf8_unicode_ci DEFAULT NULL,
  `role` varchar(10) COLLATE utf8_unicode_ci DEFAULT NULL,
  `create_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`uid`)
) ENGINE=MyISAM AUTO_INCREMENT=5 DEFAULT CHARSET=utf8 COLLATE=utf8_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `wallpaper`
--

DROP TABLE IF EXISTS `wallpaper`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `wallpaper` (
  `id` varchar(255) COLLATE utf8_unicode_ci DEFAULT NULL,
  `url` varchar(255) COLLATE utf8_unicode_ci DEFAULT NULL,
  `description` varchar(255) COLLATE utf8_unicode_ci DEFAULT NULL,
  `category` varchar(255) COLLATE utf8_unicode_ci DEFAULT NULL,
  `created_at` datetime DEFAULT NULL
) ENGINE=MyISAM DEFAULT CHARSET=utf8 COLLATE=utf8_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Current Database: `mysql`
--